FROM python:3.11.6
RUN python -m pip install --upgrade pip && \
    python -m pip install dask dask-gateway distributed numpy pandas xarray zarr netcdf4 \
    intake bokeh
