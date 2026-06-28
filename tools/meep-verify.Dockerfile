# Serial pymeep from conda-forge on a Linux image — the reliable Meep distribution path.
# Used only to VERIFY the fdtd_bridge.py Meep API calls against a real Meep; not shipped with the add-on.
FROM mambaorg/micromamba:1.5-jammy
RUN micromamba install -y -n base -c conda-forge pymeep numpy scipy && micromamba clean -a -y
ENV MPLBACKEND=Agg
WORKDIR /work
