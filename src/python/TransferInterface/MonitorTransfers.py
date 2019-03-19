
import os
import json
from rucio.common.exception import ReplicaNotFound
from RESTInteractions import HTTPRequests
from ServerUtilities import encodeRequest
from TransferInterface import chunks, mark_failed, mark_transferred, CRABDataInjector


def monitor(user, taskname, log):
        os.environ["X509_CERT_DIR"] = os.getcwd()

        proxy = None
        if os.path.exists('task_process/rest_filetransfers.txt'): 
            with open("task_process/rest_filetransfers.txt", "r") as _rest:
                rest_filetransfers = _rest.readline().split('\n')[0]
                proxy = os.getcwd() + "/" + _rest.readline()
                log.info("Proxy: %s", proxy)
                os.environ["X509_USER_PROXY"] = proxy

        if not proxy:
            log.info('No proxy available yet - waiting for first post-job')
            return None

        # TODO: what about the taskname char substitution?
        scope = "user."+user
        name = "/"+taskname.replace(":", "_")
        log.info("Initializing Monitor Rucio client for %s", taskname)
        crabInj = CRABDataInjector("", "", account=user, auth_type='x509_proxy')

        id_map = {}
        lfn_map = {}
        source_rse = {}

        if os.path.exists('task_process/transfers.txt'):
            with open('task_process/transfers.txt', 'r') as _list:
                for _data in _list.readlines():
                    try:
                        doc = json.loads(_data)
                        id_map.update({doc['destination_lfn']: doc['id']})
                        lfn_map.update({doc['id']: doc['destination_lfn']})
                        source_rse.update({doc['destination_lfn']: doc['source']+"_Temp"})
                    except Exception:
                        continue
        if os.path.exists('task_process/transfers_direct.txt'):
            with open('task_process/transfers_direct.txt', 'r') as _list:
                for _data in _list.readlines():
                    try:
                        doc = json.loads(_data)
                        id_map.update({doc['destination_lfn']: doc['id']})
                        lfn_map.update({doc['id']: doc['destination_lfn']})
                        source_rse.update({doc['destination_lfn']: doc['source']+"_Temp"})
                    except Exception:
                        continue

        try:
            rules_ = crabInj.cli.list_did_rules(scope, name)
            # {u'name': u'/store/user/dciangot/DStarToD0Pi_D0KPi_DStarFilter_TuneCP5_13TeV-pythia8-evtgen/crab_DStar_rucio_rucio_198_7/190129_085050/0000/DS2b_17_1.root', u'rse': u'T2_IT_Pisa', u'state': u'OK', u'scope': u'user.dciangot', u'rse_id': u'200b6830ca424d87a2e0ae855341b084', u'rule_id': u'4bc56a77ac6743e791dfedaa11db1e1c'}
            list_good = []
            list_failed = []
            list_failed_tmp = []
            list_stuck = []
            list_update = []

            rules = rules_.next()
            log.info("RULES %s", rules)

        except Exception:
            log.exception("Failed to retrieve rule information")
            return

        locks_generator = None
        try:
            locks_generator = crabInj.cli.examine_replication_locks(rules['id'])
        except Exception:
            if rules['state'] == 'STUCK':
                transfers = crabInj.cli.examine_replication_rule(rules['id'])['transfers']
                for lfn in transfers:
                    list_stuck.append((lfn['name'], 'Rule STUCK.'))
            else:
                log.exception('Unable to get replica locks')
                return

        sitename = None
        try:
            # TODO: split in threads ?
            for file_ in locks_generator:
                log.info("LOCK %s", file_)
                filename = file_['name']
                status = file_['state']
                log.info("state %s", status)
                sitename = file_['rse']

                if status == "OK":
                    list_good.append(filename)
                if status == "STUCK":
                    list_failed_tmp.append((filename, "Transfer Stuck", sitename))
                if status == "REPLICATING":
                    ftsJobID = crabInj.cli.list_request_by_did(filename, sitename, scope)["external_id"]
                    if ftsJobID:
                        list_update.append((filename, ftsJobID))
        except Exception:
            log.exception("Replica locks not found")

        for name_ in [x[0] for x in list_failed_tmp]:
            try:
                ftsJobID = crabInj.cli.list_request_by_did(name_, sitename, scope)["external_id"]
                if ftsJobID:
                    list_failed.append((name_, "FTS job ID: %s" % ftsJobID))
                else:
                    list_failed.append((name_, "No FTS job ID available for stuck transfers. Rucio could have failed to submit FTS job."))
            except Exception:
                log.error("No FTS job ID available for stuck transfer %s. Rucio could have failed to submit FTS job." % name_)
                list_failed.append((name_, "No FTS job ID available for stuck transfers. Rucio could have failed to submit FTS job."))

        direct_files = []
        if os.path.exists('task_process/transfers/registered_direct_files.txt'):
            with open("task_process/transfers/registered_direct_files.txt", "r") as list_file:
                direct_files = [x.split('\n')[0] for x in list_file.readlines()]
                log.debug("Checking if some failed files were directly staged from wn: {0}".format(str(direct_files)))
                list_failed = [x for x in list_failed if x[0] not in direct_files]
                log.debug("{0} files to be marked as failed.".format(str(len(list_failed))))

        try:

            oracleDB = HTTPRequests(rest_filetransfers,
                                    proxy,
                                    proxy)
        except Exception:
            log.exception("Failed to set connection to oracleDB")
            return

        try:
            if len(list_failed) > 0:
                list_failed_name = [{'scope': scope, 'name': x[0]} for x in list_failed]
                log.debug("Detaching %s" % list_failed_name)
                crabInj.cli.detach_dids(scope, name, list_failed_name)
                sources = list(set([source_rse[x['name']] for x in list_failed_name]))
                for source in sources:
                    crabInj.delete_replicas(source, [x for x in list_failed_name if source_rse[x['name']] == source])
                mark_failed([id_map[x[0]] for x in list_failed], [x[1] for x in list_failed], oracleDB)
        except ReplicaNotFound:
                try:
                    mark_failed([id_map[x[0]] for x in list_failed], [x[1] for x in list_failed], oracleDB)
                except Exception:
                    log.exception("Failed to update status for failed files")
        except Exception:
            log.exception("Failed to update status for failed files")

        try:
            if len(list_stuck) > 0:
                list_stuck_name = [{'scope': scope, 'name': x[0]} for x in list_stuck]
                log.debug("Detaching %s" % list_stuck_name)
                crabInj.cli.detach_dids(scope, name, list_stuck_name)
                sources = list(set([source_rse[x['name']] for x in list_stuck_name]))
                for source in sources:
                    crabInj.delete_replicas(source, [x for x in list_stuck_name if source_rse[x['name']] == source])
                mark_failed([id_map[x[0]] for x in list_stuck], [x[1] for x in list_stuck], oracleDB)
        except ReplicaNotFound:
                try:
                    mark_failed([id_map[x[0]] for x in list_failed], [x[1] for x in list_failed], oracleDB)
                except Exception:
                    log.exception("Failed to update status for failed files")
        except Exception:
            log.exception("Failed to update status for stuck rule")

        try:
            mark_transferred([id_map[x] for x in list_good], oracleDB)
        except Exception:
            log.exception("Failed to update status for transferred files")

        try:
            already_list = []
            list_update_filt = []
            if os.path.exists("task_process/transfers/submitted_files.txt"):
                with open("task_process/transfers/submitted_files.txt", "r") as list_file:
                    for _data in list_file.readlines():
                        already_list.append(_data.split("\n")[0])

            list_update_filt = [x for x in list_update if x not in already_list and x[0] not in direct_files]

            if len(list_update_filt) > 0:
                list_update = list_update_filt
                fileDoc = dict()
                fileDoc['asoworker'] = 'rucio'
                fileDoc['subresource'] = 'updateTransfers'
                fileDoc['list_of_ids'] = [id_map[x[0]] for x in list_update]
                fileDoc['list_of_transfer_state'] = ["SUBMITTED" for _ in list_update]
                fileDoc['list_of_fts_instance'] = ['https://fts3.cern.ch:8446/' for _ in list_update]
                fileDoc['list_of_fts_id'] = [x[1] for x in list_update]
                oracleDB.post('/filetransfers',
                              data=encodeRequest(fileDoc))
                log.debug("Marked submitted %s" % [id_map[x[0]] for x in list_update])

                with open("task_process/transfers/submitted_files.txt", "a+") as list_file:
                    for update in list_update:
                        log.debug("{0}\n".format(str(update)))
                        list_file.write("{0}\n".format(str(update)))
            else:
                log.info("Nothing to update (fts job ID)")
        except Exception:
            log.exception('Failed to update file status for FTSJobID inclusion.')

