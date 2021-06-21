#!/bin/bash

#Script submits tasks for testing. 3 types of testing can be started using this script:
# 1. Client_Validation_Suite: tests different CRABClient commands;
# 2. Client_Configuration_Validation: tests different CRABClient configurations;
# 3. Task_Submission_Status_Tracking: checks if submitted tasks finished running.
#Variabiles ${REST_Instance}, ${Client_Validation_Suite}, ${Client_Configuration_Validation} and ${Task_Submission_Status_Tracking} comes from
#the Jenkins CRABServer_ExecuteTests configuration.

set -x

#setup CRABClient
source setupCRABClient.sh

#submit tasks and based on the exit code add task name / file name respectively to submitted_tasks or failed_tasks file.
submitTasks(){
  for file_name in ${filesToSubmit};
  do
	echo -e "\nSubmitting file: $file_name"
        sed -i -e "/config.General.instance*/c\config.General.instance = \"${REST_Instance}\"" ${file_name}
        output=$(crab submit -c ${file_name} 2>&1)
        if [ $? != 0 ]; then
                echo ${file_name} >> /artifacts/failed_tasks
        else
                echo ${output} | grep -oP '(?<=Task name:\s)[^\s]*(?=)' >> /artifacts/submitted_tasks_${2}
		echo ${output} | grep -oP '(?<=Project dir:\s)[^\s]*(?=)' >> /artifacts/project_directories
        fi
        echo $output
  done
}


#run immediate check on tasks submitted for Client_Configuration_Validation testing. 
#Save results to failed_tests and successful_tests files.
immediateCheck(){
  project_dir="/tmp/crabTestConfig"
  for task in ${tasksToCheck};
  do
	echo -e "\nRunning immediate test on task: ${task}"
	test_to_execute=`echo "${task}" | grep -oP '(?<=_crab_).*(?=)'`
	task_dir=${project_dir}/crab_${test_to_execute}
	bash -x ${test_to_execute}-testSubmit.sh ${task_dir} && \
		echo ${test_to_execute}-testSubmit.sh ${task_dir} - $? >> /artifacts/successful_tests || \
		echo ${test_to_execute}-testSubmit.sh ${task_dir} - $? >> /artifacts/failed_tests	
  done
}

if [ "${Client_Validation_Suite}" = true ]; then
	echo -e "\nStarting task submission for Client Validation testing.\n"
	cd clientValidationTasks
	filesToSubmit=`find . -type f -name '*.py' ! -name '*pset*'`
	submitTasks "${filesToSubmit}" "CV"
	cd ${WORK_DIR}
fi

if [ "${Client_Configuration_Validation}" = true ]; then
	echo -e "\nStarting task submission for Client Configuration Validation testing.\n"
	mkdir -p tmpWorkDir
	cd tmpWorkDir
	python /data/CRABTesting/testingScripts/makeTests.py 
        filesToSubmit=`find . -maxdepth 1 -type f -name '*.py' ! -name '*PSET*'`
        submitTasks "${filesToSubmit}" "CCV"
	tasksToCheck=`cat /artifacts/submitted_tasks_CCV`
	immediateCheck "${tasksToCheck}" 
	cd ${WORK_DIR}
fi

if [ "${Task_Submission_Status_Tracking}" = true ]; then
	echo -e "\nStarting task submission for Status Tracking testing.\n"
	cd statusTrackingTasks
        filesToSubmit=`find . -type f -name '*.py' ! -name '*pset*'`
        submitTasks "${filesToSubmit}" "TS"
	cd ${WORK_DIR}
fi

cat /artifacts/project_directories

#in case at least one task submission failed, kill all succesfully submitted tasks.
if [ -s "/artifacts/failed_tasks" ]; then 
	echo -e "\nSome task submission failed. Killing succesfully submitted tasks.\n"
	while read task ; do
  		echo "Killing task: $task"
  		crab kill $task
	done </artifacts/project_directories
fi

