#!/bin/bash

env

# if [[ "$USER" = 'crab3' ]]; then
        echo starting
        cd /data/srv/TaskManager

        touch /data/srv/condor_config
        curl --remote-name-all https://raw.githubusercontent.com/dmwm/CRABServer/master/src/script/Deployment/TaskWorker/{start.sh,env.sh,stop.sh}
        chmod 750 start.sh env.sh stop.sh

        set -x
        echo 'Setting enviroment'

        export RELEASE=$TW_VERSION 

        export MYTESTAREA=/data/srv/TaskManager/$RELEASE
        export SCRAM_ARCH=slc7_amd64_gcc630

        export REPO=comp.belforte
        #export REPO=comp

        export verbose=true
        echo 'Installation'

        mkdir -p $MYTESTAREA
        wget -O $MYTESTAREA/bootstrap.sh http://cmsrep.cern.ch/cmssw/repos/bootstrap.sh
        sh $MYTESTAREA/bootstrap.sh -architecture $SCRAM_ARCH -path $MYTESTAREA -repository $REPO setup

        $RELEASE/common/cmspkg -a $SCRAM_ARCH upgrade
        $RELEASE/common/cmspkg -a $SCRAM_ARCH update
        $RELEASE/common/cmspkg -a $SCRAM_ARCH install cms+crabtaskworker+$RELEASE

        set +x
        echo 'Creating symlink'
        rm -f current
        ln -s $RELEASE current
        cd $MYTESTAREA

#        echo 'Make config file and stop + start '

# else
#         echo 'Please change to CRAB3 user, TW cannot be installed by root'
#         echo -ne 'switch to crab3 user: \n\tsudo -u crab3 -i bash\nand try again.\n\n'
# fi
