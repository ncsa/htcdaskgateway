# NCSA HTCdaskGateway

Subclasses the Dask Gateway client to launch dask clusters in Kubernetes, but
with HTCondor workers. This is a fork of the ingenious original idea by Maria
Acosta at Fermilab as part of their Elastic Analysis Facility project.

## ICRN Quick Start

As a user of the Illinois Computes Research Notebooks environment, you will use
conda to set up the Condor tools and install this library. Create the following
conda.yaml file:

```yaml
name: dask-gateway
channels:
  - conda-forge
  - defaults
dependencies:
  - python=3.11
  - htcondor
  - pip
  - pip:
      - ncsa-htcdaskgateway>=1.0.4
      - dask==2025.2.0
      - distributed==2025.2.0
      - tornado==6.4.2
```

From a Jupyter terminal window create the conda environment with:

```bash
conda env create -f conda.yaml
conda activate dask-gateway
```

_Note:_ Depending on your conda setup, the `conda activate` command may not be
available you can also activate the environment with the command
`source activate dask-gateway`.

Now you can use the `setup_condor` script to set up the HTCondor tools. This
will request your Illinois password and attempt to log into the HTCondor login
node and execute a command that generates a token file. This token file is used
by the HTCondor tools to authenticate with the HTCondor cluster. The script will
put the token in your `~/.condor/tokens.d` directory.

It will also write appropriate condor_config settings to the conda environment's
condor directory.

When complete, you should be able to view the condor queue from an ICRN terminal
with

```bash
condor_q
```

## Use in Jupyter Notebook

In your Jupyter notebook first thing you need to do is activate the conda
environment:

```shell
!source activate dask-gateway
```

Now you can pip install any additional dependencies. For objects that are sent
to dask or received as return values, you must have the exact same versions.

```shell
! python -m pip install numpy==2.2.4
```

### Providing Path to Condor Tools

There are some interesting interactions between conda and Jupyter. Conda has
installed the condor binaries, but doesn't update PATH in the notebook kernel.
We use an environment variable to tell the htcdaskgateway client how to find the
binaries.

In a terminal window:

```shell
source activate dask-gateway
which condor_q
```

Back in your notebook:

```python
import os

os.environ["CONDOR_BIN_DIR"] = "/home/myhome/.conda/envs/dask-gateway/bin"
```

### Setting up a dotenv file

It is good practice to keep passwords out of your notebooks. Create a `.env`
file that contains an entry for `DASK_GATEWAY_PASSWORD`

Add `python-dotenv` to your pip installed dependencies and add this line to your
notebook:

```python
from dotenv import load_dotenv

load_dotenv()  # take environment variables from .env.
```

### Connecting to the Gateway and Scaling up Cluster

Now we can finally start up a cluster!

```python
from htcdaskgateway import HTCGateway
from dask_gateway.auth import BasicAuth
import os

gateway = HTCGateway(
    address="https://dask.software-dev.ncsa.illinois.edu",
    proxy_address=8786,
    auth=BasicAuth(username=None, password=os.environ["DASK_GATEWAY_PASSWORD"]),
)

cluster = gateway.new_cluster(
    image="ncsa/dask-public-health:latest",
    container_image="/u/bengal1/condor/PublicHealth.sif",
)
cluster.scale(2)
client = cluster.get_client()
client
```

This will display the URL to access the cluster dashboard

## How it Works

This is a drop-in replacement for the official Dask Gateway client. It keeps the
same authentication and interaction with the gateway server (which is assumed to
be running in a Kubernetes cluster). When the user requests a new cluster, this
client communicates with the gateway server and instructs it to launch a
cluster. We are running a
[modified docker image](https://github.com/BenGalewsky/dask-gateway/tree/htcgateway)
in the cluster which only launches the scheduler, and assumes that HTC workers
will eventually join.

The client then uses the user's credentials to build an HTC Job file and submits
it to the cluster. These jobs run the dask worker and have the necessary certs
to present themselves to the scheduler.

The scheduler then accepts them into the cluster and we are ready to `compute`

## Preparing The Ground

There are a number of configuration steps that need to be done in order for this
configuration to work. Here are the main ones:

1. The workers communicate with the scheduler via TLS connection on port 8786.
   The Kubernetes traefik ingress needs to know about this port and route
   traffic from it
2. The scheduler need to be able to communicate with the workers and the workers
   need to communicate with each other. This happens on a range of ports which
   need to be opened up
3. The client library submits jobs to the HTCondor cluster. This means that the
   user environment must be configured to submit and manage HTCJobs

### HTCondor Integration

The client library creates a job file and a shell script to run the dask worker.
These files need to be in a spot that is readable by HTCondor worker nodes.

The condor tools (condor_submit, condor_q, and condor_rm) require some
configuration and a token file in order to operate with the cluster.

### Usage:

At a minimum, the client environment will need to install:

1. This library: `ncsa-htcdaskgateway`
2. dask

Connect to the gateway and create a cluster:

```python
from htcdaskgateway import HTCGateway
from dask_gateway.auth import BasicAuth

gateway = HTCGateway(
    address="https://dask.software-dev.ncsa.illinois.edu",
    proxy_address=8786,
    auth=BasicAuth(username=None, password="____________"),
)

cluster = gateway.new_cluster(
    image="ncsa/dask-public-health:latest",
    container_image="/u/bengal1/condor/PublicHealth.sif",
)
cluster.scale(4)

client = cluster.get_client()
```

Hopefully your environment will have more secure auth model than this....

The `image` argument is the docker image the scheduler will run in. The
`container_image` argument is the path to an Apptainer image the HTCondor worker
will run in.

In order for the `image` argument to work, you need to deploy the gateway with
the image customization enabled:

```yaml
gateway:
  # The gateway server log level
  loglevel: INFO

  extraConfig:
    # Enable scheduler image name to be provided by the client cluster constructor
    image-customization: |
      from dask_gateway_server.options import Options, String

      def option_handler(options):
          return {
              "image": options.image,
              # Add other options as needed
          }

      c.Backend.cluster_options = Options(
          String("image", default="daskgateway/dask-gateway:latest", label="Image"),
          # Add other option parameters as needed
          handler=option_handler,
      )
```

# Notes from FNAL Implementation

- A Dask Gateway client extension for heterogeneous cluster mode combining the
  Kubernetes backend for pain-free scheduler networking, with COFFEA-powered
  HTCondor workers and/or OKD [coming soon].
- Latest
  [![PyPI version](https://badge.fury.io/py/htcdaskgateway.svg)](https://badge.fury.io/py/htcdaskgateway)
  is installed by default and deployed to the COFFEA-DASK notebook on EAF
  (https://analytics-hub.fnal.gov). A few lines will get you going!
- The current image for workers/schedulers is:
  coffeateam/coffea-dask-cc7-gateway:0.7.12-fastjet-3.3.4.0rc9-g8a990fa

## Basic usage @ Fermilab [EAF](https://analytics-hub.fnal.gov)

- Make sure the notebook launched supports this functionality (COFFEA-DASK
  notebook)

```
from htcdaskgateway import HTCGateway

gateway = HTCGateway()
cluster = gateway.new_cluster()
cluster

# Scale my cluster to 5 HTCondor workers
cluster.scale(5)

# Obtain a client for connecting to your cluster scheduler
# Your cluster should be ready to take requests
client = cluster.get_client()
client

# When computations are finished, shutdown the cluster
cluster.shutdown()
```

## Other functions worth checking out

- This is a multi-tenant environment, and you are authenticated via JupyterHub
  Oauth which means that you can create as many\* clusters as you wish
- To list your clusters:

```
# Verify that the gateway is responding to requests by asking to list all its clusters
clusters = gateway.list_clusters()
clusters
```

- To connect to a specific cluster from the list:

```
cluster = gateway.connect(cluster_name)
cluster
cluster.shutdown()
```

- To gracefully close the cluster and remove HTCondor worker jobs associated to
  it:

```
cluster.shutdown()
```

- There are widgets implemented by Dask Gateway. Make sure to give them a try
  from your EAF COFFEA notebook, just execute the `client` and `cluster`
  commands (after properly initializing them) in a cell like:

```
-------------
cluster = gateway.new_cluster()
cluster
< Widget will appear after this step>
-------------
client = cluster.get_client()
client
< Widget will appear after this step >
-------------
cluster
< Widget will appear after this step >
```
