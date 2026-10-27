"""Creates the output DGN from the configured 3D seed file (copy of the seed, as
MicroStation's File > New does).  Runs with plain Python or inside MicroStation.

    python microstation/prepare_dgn.py [--seed <seed.dgn>] [--force]
    python load "<repo>\\microstation\\prepare_dgn.py"

Seed resolution: --seed, then ``files.dgn_seed`` in config/model_config.yaml,
then (inside MicroStation) the configuration variable named in
``files.seed_config_variable`` (MS_DESIGNSEED).  An existing output file is
never overwritten unless --force is given and it is not the active file.
Afterwards open the file in MicroStation (File > Open) and run
build_railway_dgn.py.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.config import load_config, repo_path  # noqa: E402


def resolve_seed(cfg, cli_seed=None) -> str:
    if cli_seed:
        return cli_seed
    if cfg.model["files"].get("dgn_seed"):
        return repo_path(cfg.model["files"]["dgn_seed"])
    try:
        from microstation.msapi import MICROSTATION_AVAILABLE, get_config_variable
        if MICROSTATION_AVAILABLE:
            v = get_config_variable(cfg.model["files"]["seed_config_variable"])
            if v:
                return v
    except Exception:
        pass
    raise SystemExit("No seed file: set files.dgn_seed in config/model_config.yaml or pass --seed")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed")
    ap.add_argument("--force", action="store_true")
    a, _ = ap.parse_known_args(argv if argv is not None else sys.argv[1:])
    cfg = load_config()
    seed = resolve_seed(cfg, a.seed)
    out = cfg.file("dgn_output")
    if not os.path.isfile(seed):
        raise SystemExit("Seed file not found: %s" % seed)
    if os.path.exists(out):
        active = None
        try:
            from MSPyMstnPlatform import ISessionMgr
            active = str(ISessionMgr.GetActiveDgnFile().GetFileName())
        except Exception:
            pass
        if not a.force:
            print("Utfilen finns redan (skrivs inte över): %s" % out)
            return out
        if active and os.path.normcase(os.path.abspath(active)) == os.path.normcase(os.path.abspath(out)):
            raise SystemExit("The output DGN is the active file - close it before --force")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    shutil.copyfile(seed, out)
    print("Skapad från seed %s:\n  %s\nÖppna filen i MicroStation (File > Open) och kör build_railway_dgn.py." % (seed, out))
    return out


if __name__ == "__main__":
    main()
