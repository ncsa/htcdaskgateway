from __future__ import annotations

import logging
import os
import pwd
import subprocess
import sys
from pathlib import Path

# @author Maria A. - mapsacosta
from dask_gateway import GatewayCluster

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger("htcdaskgateway.GatewayCluster")


class HTCGatewayCluster(GatewayCluster):
    def __init__(self, container_image=None, **kwargs):
        self.scheduler_proxy_ip = kwargs.pop("", "dask.software-dev.ncsa.illinois.edu")
        self.batchWorkerJobs = []
        self.cluster_options = kwargs.get("cluster_options")
        self.container_image = container_image

        super().__init__(**kwargs)

    # We only want to override what's strictly necessary, scaling and adapting are the most important ones

    async def _stop_async(self):
        self.destroy_all_batch_clusters()
        await super()._stop_async()

        self.status = "closed"

    def scale(self, n, **kwargs):
        """Scale the cluster to ``n`` workers.
        Parameters
        ----------
        n : int
            The number of workers to scale to.
        """
        worker_type = "htcondor"
        try:
            if "condor" in worker_type:
                self.batchWorkerJobs = []
                logger.info(" Scaling: %d HTCondor workers", n)
                self.batchWorkerJobs.append(self.scale_batch_workers(n))
                logger.debug(" New Cluster state ")
                logger.debug(self.batchWorkerJobs)
                return self.gateway.scale_cluster(self.name, n, **kwargs)

        except Exception:
            logger.error(
                "A problem has occurred while scaling via HTCondor, please check your proxy credentials"
            )
            return False

    def scale_batch_workers(self, n):
        username = pwd.getpwuid(os.getuid())[0]
        security = self.security
        cluster_name = self.name
        tmproot = f"./stage/{username}/{cluster_name}"
        condor_logdir = f"{tmproot}/condor"
        credentials_dir = f"{tmproot}/dask-credentials"
        worker_space_dir = f"{tmproot}/dask-worker-space"

        Path(tmproot).mkdir(parents=True, exist_ok=True)
        Path(condor_logdir).mkdir(parents=True, exist_ok=True)
        Path(credentials_dir).mkdir(parents=True, exist_ok=True)
        Path(worker_space_dir).mkdir(parents=True, exist_ok=True)

        with Path(credentials_dir).joinpath("dask.crt").open("w") as f:
            f.write(security.tls_cert)
        with Path(credentials_dir).joinpath("dask.pem").open("w") as f:
            f.write(security.tls_key)

        # Prepare JDL
        jdl = (
            """executable = start.sh
arguments = """
            + cluster_name
            + """ htcdask-worker_$(Cluster)_$(Process)
output = condor/htcdask-worker$(Cluster)_$(Process).out
error = condor/htcdask-worker$(Cluster)_$(Process).err
log = condor/htcdask-worker$(Cluster)_$(Process).log
request_cpus = 4
request_memory = 32GB
container_image="""
            + self.container_image
            + """
should_transfer_files = yes
transfer_input_files = ./dask-credentials, ./dask-worker-space , ./condor
when_to_transfer_output = ON_EXIT_OR_EVICT
Queue """
            + str(n)
            + """
"""
        )

        with Path(tmproot).joinpath("htcdask_submitfile.jdl").open("w+") as f:
            f.writelines(jdl)

        # Prepare singularity command
        singularity_cmd = (
            """#!/bin/bash
export APPTAINERENV_DASK_GATEWAY_WORKER_NAME=$2
export APPTAINERENV_DASK_GATEWAY_API_URL="https://dask.software-dev.ncsa.illinois.edu/api"
export APPTAINERENV_DASK_GATEWAY_CLUSTER_NAME=$1
#export APPTAINERENV_DASK_DISTRIBUTED__LOGGING__DISTRIBUTED="info"

worker_space_dir=${PWD}/dask-worker-space/$2
mkdir -p $worker_space_dir
hostname -i
DASK_LOGGING__DISTRIBUTED=info dask worker --name $2 --tls-ca-file dask-credentials/dask.crt --tls-cert dask-credentials/dask.crt --tls-key dask-credentials/dask.pem --worker-port 10000:10070 --no-nanny --scheduler-sni daskgateway-"""
            + cluster_name
            + """ --nthreads 1 tls://"""
            + self.scheduler_proxy_ip
            + """:8786"""
        )

        with Path(tmproot).joinpath("start.sh").open("w+") as f:
            f.writelines(singularity_cmd)

        Path(tmproot).joinpath("start.sh").chmod(0o775)

        logger.info(" Sandbox : %s", tmproot)
        # logger.info(" Using image: "+image_name)
        logger.debug(" Submitting HTCondor job(s) for %d workers", n)

        # We add this to avoid a bug on Farruk's condor_submit wrapper (a fix is in progress)
        os.environ["LS_COLORS"] = "ExGxBxDxCxEgEdxbxgxcxd"
        # Submit our jdl, print the result and call the cluster widget
        cmd = ". ~/.profile && condor_submit htcdask_submitfile.jdl | grep -oP '(?<=cluster )[^ ]*'"
        logger.info(
            " Submitting HTCondor job(s) for %d workers with command: %s", n, cmd
        )
        call = subprocess.check_output(["sh", "-c", cmd], cwd=tmproot)

        worker_dict = {}
        clusterid = call.decode().rstrip()[:-1]
        worker_dict["ClusterId"] = clusterid
        worker_dict["Iwd"] = tmproot
        try:
            cmd = (
                ". ~/.profile && condor_q "
                + clusterid
                + " -af GlobalJobId | awk '{print $1}'| awk -F '#' '{print $1}' | uniq"
            )
            call = subprocess.check_output(["sh", "-c", cmd], cwd=tmproot)
        except subprocess.CalledProcessError:
            logger.error(
                "Error submitting HTCondor jobs, make sure you have a valid proxy and try again"
            )
            return None
        scheddname = call.decode().rstrip()
        worker_dict["ScheddName"] = scheddname

        logger.info(
            " Success! submitted HTCondor jobs to %s with  ClusterId %s",
            scheddname,
            clusterid,
        )
        return worker_dict

    def destroy_batch_cluster_id(self, clusterid):
        logger.info(" Shutting down HTCondor worker jobs from cluster %s", clusterid)
        cmd = (
            ". ~/.profile && condor_rm "
            + self.batchWorkerJobs["ClusterId"]
            + " -name "
            + self.batchWorkerJobs["ScheddName"]
        )
        result = subprocess.check_output(
            ["sh", "-c", cmd], cwd=self.batchWorkerJobs["Pwd"]
        )
        logger.info(result.decode().rstrip())

    def destroy_all_batch_clusters(self):
        logger.info(" Shutting down HTCondor worker jobs (if any)")
        if not self.batchWorkerJobs:
            return

        for htc_cluster in self.batchWorkerJobs:
            try:
                cmd = (
                    ". ~/.profile && condor_rm "
                    + htc_cluster["ClusterId"]
                    + " -name "
                    + htc_cluster["ScheddName"]
                )
                result = subprocess.check_output(
                    ["sh", "-c", cmd], cwd=htc_cluster["Iwd"]
                )
                logger.info(result.decode().rstrip())
            except Exception:
                logger.info(result.decode().rstrip())

    def adapt(self, minimum=None, maximum=None, active=True, **kwargs):
        """Configure adaptive scaling for the cluster.
        Parameters
        ----------
        minimum : int, optional
            The minimum number of workers to scale to. Defaults to 0.
        maximum : int, optional
            The maximum number of workers to scale to. Defaults to infinity.
        active : bool, optional
            If ``True`` (default), adaptive scaling is activated. Set to
            ``False`` to deactivate adaptive scaling.
        """
        #        print("Hello, I am the interrupted adapt method")
        #        print("I have two functions:")
        #        print("1. Communicate to the Gateway server the new cluster state")
        #        print("2. Call the adapt_cluster method on my HTCGateway")

        return self.gateway.adapt_cluster(
            self.name, minimum=minimum, maximum=maximum, active=active, **kwargs
        )
