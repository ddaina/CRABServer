
import os
from RESTInteractions import HTTPRequests
from ServerUtilities import encodeRequest
from TransferInterface import chunks, mark_failed, CRABDataInjector
from WMCore.Services.PhEDEx.PhEDEx import PhEDEx
import threading


def submit(trans_tuple, job_data, log, direct=False):
    """
    submit tranfer jobs

    - group files to be transferred by source site
    - prepare jobs chunks of max 200 transfers
    - submit fts job

    :param context: fts client context
    :param toTrans: [source pfn,destination pfn, oracle file id, source site]
    :return: list of jobids submitted
    """
    threadLock = threading.Lock()
    threads = []
    to_update = []

    toTrans = trans_tuple[0]
    columns = trans_tuple[1]
    proxy = job_data['proxy']
    rest_filetransfers = job_data['rest']
    user = job_data['username']
    destination = job_data['destination']
    taskname = job_data['taskname']

    try:
        phedex = PhEDEx(responseType='xml',
                        httpDict={'key': proxy,
                                  'cert': proxy})
    except Exception:
        log.exception('PhEDEx exception.')
        return

    sources = list(set([x[columns.index('source')] for x in toTrans]))

    os.environ["X509_CERT_DIR"] = os.getcwd()
    log.info("Connection to %s with proxy in:\n %s" % (rest_filetransfers,proxy))
    oracleDB = HTTPRequests(rest_filetransfers,
                            proxy,
                            proxy)
                            #verbose=True)

    for source in sources:

        ids = [x[columns.index('id')] for x in toTrans if x[columns.index('source')] == source]
        src_lfns = [x[columns.index('source_lfn')] for x in toTrans if x[columns.index('source')] == source]
        dst_lfns = [x[columns.index('destination_lfn')] for x in toTrans if x[columns.index('source')] == source]

        sorted_source_pfns = []
        sorted_dest_lfns = []
        sorted_dest_pfns = []

        try:
            for chunk in chunks(src_lfns, 10):
                unsorted_source_pfns = [[k[1], str(x)] for k, x in phedex.getPFN(source, chunk).items()]
                for order_lfn in chunk:
                    for lfn, pfn in unsorted_source_pfns:
                        if order_lfn == lfn:
                            sorted_source_pfns.append(pfn)
                            break

            for chunk in chunks(dst_lfns, 10):
                unsorted_dest_pfns = [[k[1], str(x)] for k, x in phedex.getPFN(toTrans[0][4], chunk).items()]
                for order_lfn in chunk:
                    for lfn, pfn in unsorted_dest_pfns:
                        if order_lfn == lfn:
                            sorted_dest_pfns.append(pfn)
                            sorted_dest_lfns.append(lfn)
                            break

        except Exception as ex:
            log.error("Failed to map lfns to pfns: %s", ex)
            mark_failed(ids, ["Failed to map lfn to pfn: " + str(ex) for _ in ids], oracleDB)

        source_pfns = sorted_source_pfns
        dest_lfns = sorted_dest_lfns

        filesizes = [x[columns.index('filesize')] for x in toTrans if x[columns.index('source')] == source]
        checksums = [x[columns.index('checksums')] for x in toTrans if x[columns.index('source')] == source]

        jobs = zip(source_pfns, dest_lfns, ids, checksums, filesizes)
        job_columns = ['source_pfns', 'dest_lfns', 'ids', 'checksums', 'filesizes']

        tx_from_source = [[job, source, taskname, user, destination] for job in jobs]
        tx_columns = ['job', 'source', 'taskname', 'user', 'destination']

        for files in chunks(tx_from_source, 200):
            if not direct:
                log.info("Submitting: %s", files)
                thread = submit_thread(threadLock,
                                    log,
                                    (files, tx_columns),
                                    job_columns,
                                    proxy,
                                    to_update)
                thread.start()
                threads.append(thread)
            elif direct:
                log.info("Registering direct stageout: %s", files)
                thread = submit_thread(threadLock,
                                    log,
                                    (files, tx_columns),
                                    job_columns,
                                    proxy,
                                    to_update,
                                    direct=True)
                thread.start()
                threads.append(thread)

    for t in threads:
        t.join()

    for fileDoc in to_update:
        try:
            log.debug("%s/filetransfers?%s" % (rest_filetransfers, encodeRequest(fileDoc)))
            oracleDB.post('/filetransfers', data=encodeRequest(fileDoc))
            log.info("Marked submitted %s files" % (fileDoc['list_of_ids']))
        except Exception:
            log.exception('Failed to mark files as submitted on DBs')

    return


class submit_thread(threading.Thread):
    """

    """
    def __init__(self, threadLock, log, files, job_column, proxy, toUpdate, direct=False):
        """

        :param threadLock:
        :param log:
        :param context:
        :param files:
        :param source:
        :param jobids:
        :param toUpdate:
        """
        threading.Thread.__init__(self)
        self.log = log
        self.direct = direct
        self.proxy = proxy
        self.threadLock = threadLock
        self.files = files[0]
        self.file_col = files[1]
        self.job = [x[0] for x in self.files]
        self.job_col = job_column
        self.source = self.files[0][self.file_col.index('source')]
        self.toUpdate = toUpdate
        self.taskname = self.files[0][self.file_col.index('taskname')].replace(":", "_")
        self.username = self.files[0][self.file_col.index('user')]
        self.destination = self.files[0][self.file_col.index('destination')]
        self.scope = 'user.' + self.username

    def run(self):
        """

        """

        self.threadLock.acquire()
        self.log.info("Processing transfers from: %s" % self.source)

        self.log.info("Submitting %s transfers to FTS server" % len(self.files))

        try:
            os.environ["X509_USER_PROXY"] = self.proxy
            self.log.info("Initializing Rucio client for %s", self.taskname)
            crabInj = CRABDataInjector(self.taskname, self.destination, account=self.username, scope=self.scope, auth_type='x509_proxy')
            self.log.info("Checking for current dataset")
            crabInj.cli.get_did(self.scope, self.taskname)
        except Exception as ex:
            self.log.warn("Failed to find dataset %s:%s On Rucio server: %s", "user.%s" % self.username, self.taskname, ex)
            try:
                crabInj.add_dataset()
            except Exception as ex:
                self.log.error("Failed to create dataset %s:%s on Rucio server: %s", "user.%s" % self.taskname, self.taskname, ex)
                self.threadLock.release()
                return
        try:
            # TODO: pass crabInj to threads
            self.log.debug(self.job_col)
            dest_lfns = [x[self.job_col.index('dest_lfns')] for x in self.job]
            source_pfns = [x[self.job_col.index('source_pfns')] for x in self.job]

            self.log.info(self.source+"_Temp")
            self.log.info(dest_lfns)
            self.log.info(source_pfns)

            sizes = [x[self.job_col.index('filesizes')] for x in self.job]

            # TODO: actual checksum format not accepted by RUCIO
            # checksums = [x[7] for x in self.files]

            if self.direct:
                try:
                    self.log.info("Registering direct files")
                    crabInj.register_crab_replicas(self.destination, dest_lfns, sizes, None)
                    crabInj.attach_files(dest_lfns, self.taskname)
                    self.log.info("Registered {0} direct files.".format(len(dest_lfns)))
                    self.log.debug("Registered direct files: {0}".format(dest_lfns))
                    self.threadLock.release()
                    return
                except Exception:
                    self.log.exception("Failed to register direct files.")
                    self.threadLock.release()
                    return

            self.log.info("Registering temp file")
            # crabInj.register_temp_replicas(self.source+"_Temp", dest_lfns, source_pfns, sizes, checksums)
            crabInj.register_temp_replicas(self.source+"_Temp", dest_lfns, source_pfns, sizes, None)
            crabInj.attach_files(dest_lfns, self.taskname)

        except Exception:
            self.log.exception("Failed to register replicas")
            self.threadLock.release()
            return

        try:
            fileDoc = dict()
            fileDoc['asoworker'] = 'rucio'
            fileDoc['subresource'] = 'updateTransfers'
            fileDoc['list_of_ids'] = [x[self.job_col.index('ids')] for x in self.job]
            fileDoc['list_of_transfer_state'] = ["SUBMITTED" for _ in self.files]
            fileDoc['list_of_fts_instance'] = ['https://fts3.cern.ch:8446/' for _ in self.job]
            fileDoc['list_of_fts_id'] = ['NA' for _ in self.job]

            self.log.info("Marking submitted %s files" % (len(fileDoc['list_of_ids'])))
            self.toUpdate.append(fileDoc)
        except Exception:
            self.log.exception("Failed to update status in oracle")
            self.threadLock.release()
            return

        self.threadLock.release()
