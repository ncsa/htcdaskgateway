from __future__ import annotations

import logging
import sys

# @author Maria A. - mapsacosta
from dask_gateway import Gateway

# from .options import Options
from .cluster import HTCGatewayCluster

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger("htcdaskgateway.HTCGateway")


class HTCGateway(Gateway):
    def __init__(self, **kwargs):
        address = kwargs.pop("address", "https://dask.software-dev.ncsa.illinois.edu")
        super().__init__(address, **kwargs)

    def new_cluster(
        self,
        cluster_options=None,
        shutdown_on_close=True,
        container_image=None,
        **kwargs,
    ):
        """Submit a new cluster to the gateway, and wait for it to be started.
        Same as calling ``submit`` and ``connect`` in one go.
        Parameters
        ----------
        cluster_options : dask_gateway.options.Options, optional
            An ``Options`` object describing the desired cluster configuration.
        shutdown_on_close : bool, optional
            If True (default), the cluster will be automatically shutdown on
            close. Set to False to have cluster persist until explicitly
            shutdown.
        container_image : str, Path to the apptainer image to run in the workers
        **kwargs :
            Additional cluster configuration options. If ``cluster_options`` is
            provided, these are applied afterwards as overrides. Available
            options are specific to each deployment of dask-gateway, see
            ``cluster_options`` for more information.
        Returns
        -------
        cluster : GatewayCluster
        """
        logger.info(" Creating HTCGatewayCluster ")
        return HTCGatewayCluster(
            address=self.address,
            proxy_address=self.proxy_address,
            auth=self.auth,
            asynchronous=self.asynchronous,
            loop=self.loop,
            shutdown_on_close=shutdown_on_close,
            cluster_options=cluster_options,
            container_image=container_image,
            **kwargs,
        )

    def scale_cluster(self, cluster_name, n, worker_type, **kwargs):
        """Scale a cluster to n workers.
        Parameters
        ----------
        cluster_name : str
            The cluster name.
        n : int
            The number of workers to scale to.
        """
        assert worker_type == "htcondor"
        return self.sync(self._scale_cluster, cluster_name, n, **kwargs)

    async def _stop_cluster(self, cluster_name):
        url = f"{self.address}/api/v1/clusters/{cluster_name}"
        await self._request("DELETE", url)
        HTCGatewayCluster.from_name(cluster_name).close(shutdown=True)

    def stop_cluster(self, cluster_name, **kwargs):
        """Stop a cluster.
        Parameters
        ----------
        cluster_name : str
            The cluster name.
        """
        return self.sync(self._stop_cluster, cluster_name, **kwargs)
