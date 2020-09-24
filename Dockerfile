FROM cmssw/cmsweb:20200715
MAINTAINER Daina Dirmaite daina.dirmaite@gmail.com

#keep only voms-proxy basded on c++
RUN yum remove -y voms-clients-java && yum -y install strace \
gfal2-util gfal2-all \
vim \
&& yum clean all && rm -rf /var/cache/yum

ENV WDIR=/data
ENV USER=crab3

# add new user and switch to user
RUN useradd ${USER} && install -o ${USER} -d ${WDIR}
USER ${USER}

ARG TW_VERSION
ENV RELEASE $TW_VERSION
ENV TW_VERSION $TW_VERSION

RUN mkdir -p /data/srv/tmp && mkdir -p /data/srv/TaskManager
WORKDIR ${WDIR}

# install
RUN curl -o install.sh https://raw.githubusercontent.com/ddaina/CMSKubernetes/crabtaskworker/docker/crabtaskworker/install.sh
#COPY --chown=${USER}:${USER} install.sh .
RUN echo "Y" > yes.repo && sh install.sh < yes.repo

WORKDIR ${WDIR}/srv/TaskManager/

# run the service
CMD source ${WDIR}/srv/TaskManager/start.sh && while true; do sleep 60;done
