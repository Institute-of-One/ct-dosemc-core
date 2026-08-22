"""Apply the Route A (@manifest + load_voxels memo) patch to an MC-GPU .cu file.

This is a **performance** modification, not a defect fix. Defects #22-#26
change physics or silently wrong results; Route A only hoists the geometry
parse out of the sub-fan loop. Transport, RNG and per-beam tallies are
unchanged (byte-equality vs a standalone invocation).

Per-beam ``fclose`` of the input and spectrum FILE* is part of Route A, not of
upstream physics: a standalone process exits and the CRT reclaims them; a
2016-beam Route A process hits the MSVC 512-handle cap around beam 255.

``tools/build_mcgpu.ps1`` copies upstream to ``win_{cpu,gpu}.cu`` and then runs
this, so both targets get the same definition.  Idempotent: a file that already
has the patch is left unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARKER = "=== Route A: expand an optional manifest"

LOOP_START = r"""
  // === Route A: expand an optional manifest of input files into a beam list ===
  // If argv[1] is "@manifest", every non-comment line of the manifest names one
  // MC-GPU input file; they are simulated sequentially in this single process so
  // the shared voxel geometry is parsed once (see load_voxels memoization). This
  // is the sub-fan decomposition with only the geometry parse hoisted out of the
  // P*K loop -- the estimator is identical to running each input on its own
  // (MC_SOURCE_MODEL.md 5.3.0e). Without a leading "@", behaviour is unchanged.
  int routeA_num_beams = 1;
  char** routeA_beam_files = (char**) malloc(sizeof(char*));
  routeA_beam_files[0] = (argc>1) ? argv[1] : NULL;
  if (argc>1 && argv[1][0]=='@')
  {
    FILE* routeA_mf = fopen(argv[1]+1, "r");
    if (NULL==routeA_mf)
    {
      printf("\n\n   !!ERROR!! Route A manifest '%s' not readable.\n\n", argv[1]+1);
      exit(-2);
    }
    #define ROUTEA_MAX_BEAMS 200000
    free(routeA_beam_files);
    routeA_beam_files = (char**) malloc(ROUTEA_MAX_BEAMS*sizeof(char*));
    routeA_num_beams = 0;
    char routeA_mline[300];
    while (fgets(routeA_mline, 300, routeA_mf)!=NULL)
    {
      char* routeA_p = routeA_mline;
      while (*routeA_p==' ' || *routeA_p=='\t') routeA_p++;
      size_t routeA_L = strlen(routeA_p);
      while (routeA_L>0 && (routeA_p[routeA_L-1]=='\n' || routeA_p[routeA_L-1]=='\r' || routeA_p[routeA_L-1]==' ' || routeA_p[routeA_L-1]=='\t')) { routeA_p[--routeA_L] = '\0'; }
      if (routeA_L==0 || routeA_p[0]=='#') continue;
      routeA_beam_files[routeA_num_beams] = (char*) malloc(routeA_L+1);
      strcpy(routeA_beam_files[routeA_num_beams], routeA_p);
      routeA_num_beams++;
      if (routeA_num_beams>=ROUTEA_MAX_BEAMS) break;
    }
    fclose(routeA_mf);
    MASTER_THREAD printf("\n    -- [Route A] batch mode: %d input files from manifest '%s' (voxel geometry parsed once).\n", routeA_num_beams, argv[1]+1);
  }

  int routeA_beam;
  for (routeA_beam=0; routeA_beam<routeA_num_beams; routeA_beam++)
  {
    argv[1] = routeA_beam_files[routeA_beam];
    if (routeA_num_beams>1)
      MASTER_THREAD printf("\n\n========== [Route A] beam %d / %d : %s ==========\n\n", routeA_beam+1, routeA_num_beams, argv[1]);
    // === Route A: per-beam tally reset ===
    // Each beam writes its own dose file. Accumulating into one tally would
    // collapse the unequal Omega_k weights (MC_SOURCE_MODEL.md 5.3.0e).
    time_total_MC_simulation = 0.0;
    time_elapsed_MC_loop = 0.0;
    for(kk=0;kk<MAX_MATERIALS;kk++)
    {
      materials_dose[kk].x = 0;
      materials_dose[kk].y = 0;
    }

"""

LOOP_END = r"""
  }  // === Route A: end of the per-beam loop (geometry parsed once, above) ===

  // -- Release the beam list built from the manifest (the strings for a single
  //    input point into argv and must not be freed).
  if (routeA_num_beams>1)
  {
    for (routeA_beam=0; routeA_beam<routeA_num_beams; routeA_beam++) free(routeA_beam_files[routeA_beam]);
  }
  free(routeA_beam_files);

"""

LOAD_CACHE_HEAD = r"""
  // === Route A: memoized geometry parse (MC_SOURCE_MODEL.md 5.3.0e) ===
  // The ~58M-voxel ASCII parse dominates per-invocation init. When the sub-fan
  // decomposition drives P*K beams that all share one voxel file, re-parsing it
  // every beam is the whole 144-invocation performance wall. Cache the parsed
  // geometry keyed by filename and hand every later beam a fresh malloc'd copy of
  // the identical arrays, so the transport is byte-for-byte what a standalone
  // invocation would produce -- only the parse is skipped, nothing else changes.
  static int   routeA_vox_valid = 0;
  static char  routeA_vox_name[250] = "";
  static struct voxel_struct routeA_vox_data;
  static float2* routeA_vox_arr = NULL;
  static unsigned int routeA_vox_bytes = 0;
  static float routeA_vox_dmax[MAX_MATERIALS];
  static short int routeA_vox_rx = 0, routeA_vox_ry = 0, routeA_vox_rz = 0;
  if (routeA_vox_valid && 0==strcmp(routeA_vox_name, file_name_voxels))
  {
    int routeA_m;
    *voxel_data           = routeA_vox_data;
    *voxel_mat_dens_bytes = routeA_vox_bytes;
    *voxel_mat_dens_ptr   = (float2*) malloc(routeA_vox_bytes);
    if (NULL==*voxel_mat_dens_ptr)
    {
      printf("\n\n   !!malloc ERROR load_voxels (Route A cache copy)!! %u bytes\n\n", routeA_vox_bytes);
      exit(-2);
    }
    memcpy(*voxel_mat_dens_ptr, routeA_vox_arr, routeA_vox_bytes);
    for (routeA_m=0; routeA_m<MAX_MATERIALS; routeA_m++) density_max[routeA_m] = routeA_vox_dmax[routeA_m];
    *dose_ROI_x_max = routeA_vox_rx; *dose_ROI_y_max = routeA_vox_ry; *dose_ROI_z_max = routeA_vox_rz;
    MASTER_THREAD printf("\n    -- [Route A] reusing cached voxel geometry '%s' (%f MB); ASCII parse skipped.\n", file_name_voxels, routeA_vox_bytes/(1024.f*1024.f));
    return;
  }

"""

LOAD_CACHE_TAIL = r"""
  // === Route A: store the parsed geometry so later beams reuse it (see top) ===
  {
    int routeA_m;
    routeA_vox_data  = *voxel_data;
    routeA_vox_bytes = *voxel_mat_dens_bytes;
    if (routeA_vox_arr!=NULL) free(routeA_vox_arr);
    routeA_vox_arr = (float2*) malloc(routeA_vox_bytes);
    if (routeA_vox_arr!=NULL) memcpy(routeA_vox_arr, *voxel_mat_dens_ptr, routeA_vox_bytes);
    for (routeA_m=0; routeA_m<MAX_MATERIALS; routeA_m++) routeA_vox_dmax[routeA_m] = density_max[routeA_m];
    routeA_vox_rx = *dose_ROI_x_max; routeA_vox_ry = *dose_ROI_y_max; routeA_vox_rz = *dose_ROI_z_max;
    strncpy(routeA_vox_name, file_name_voxels, 249); routeA_vox_name[249] = '\0';
    routeA_vox_valid = (routeA_vox_arr!=NULL) ? 1 : 0;
  }
"""

DECL = (
    "  char file_name_voxels[250], file_name_materials[MAX_MATERIALS][250], "
    "file_name_output[250], file_dose_output[250], file_name_espc[250];"
)
READ_INPUT = "  // *** Read the input file given in the command line and return the significant data:"
CLEAN_ENDIF = "#endif\n   \n\n#ifdef USING_MPI\n  MPI_Finalize();   // Finalize MPI library: no more MPI calls allowed below."
LOAD_OPEN = "  char *new_line_ptr = NULL;  \n      \n  MASTER_THREAD if (strstr(file_name_voxels,\".zip\")!=NULL)"
LOAD_CLOSE = (
    '  MASTER_THREAD printf("       Total number of voxels read: %d\\n",read_lines);\n'
    "  gzclose(file_ptr);     // Close input file    !!zlib!!\n"
    "}"
)

FCLOSE_MARK = "Route A: fclose input and spectrum per beam"

READ_INPUT_RETURN = (
    "    memset(*voxels_Edep_ptr, 0, (*voxels_Edep_bytes));     // Init memory space to 0.\n"
    "  }\n"
    "\n"
    "  return;\n"
    "}"
)
READ_INPUT_FCLOSE = (
    "    memset(*voxels_Edep_ptr, 0, (*voxels_Edep_bytes));     // Init memory space to 0.\n"
    "  }\n"
    "\n"
    "  fclose(file_ptr);  // Route A: fclose input and spectrum per beam\n"
    "  return;\n"
    "}"
)
SPECTRUM_IRND0 = (
    "  IRND0(prob_espc_bin, source_energy_data->espc_cutoff, "
    "source_energy_data->espc_alias, source_energy_data->num_bins_espc);   "
    "//!!Walker!! Calling PENELOPE's function to init the Walker method"
)
SPECTRUM_FCLOSE = (
    SPECTRUM_IRND0 + "\n  fclose(file_ptr);  // Route A: fclose input and spectrum per beam"
)


def _nl(text: str) -> str:
    return "\r\n" if "\r\n" in text[:8000] else "\n"


def _ensure_fclose(text: str) -> tuple[str, int]:
    """Close the per-beam input and spectrum FILE* that Route A reopens.

    Upstream never fclose'd them because a standalone process exits. Route A
    runs thousands of beams in one process; MSVC fopen fails after 512 FILE*.
    144-beam G2 stayed under the cap; z-station manifests (14 x 144 = 2016)
    die around beam 255. fclose only; the transport is unchanged.
    """
    lf = text.replace("\r\n", "\n")
    n = 0
    if READ_INPUT_FCLOSE not in lf:
        if READ_INPUT_RETURN not in lf:
            raise ValueError("read_input return anchor not found for fclose")
        lf = lf.replace(READ_INPUT_RETURN, READ_INPUT_FCLOSE, 1)
        n += 1
    if SPECTRUM_FCLOSE not in lf:
        if SPECTRUM_IRND0 not in lf:
            raise ValueError("init_energy_spectrum IRND0 anchor not found for fclose")
        lf = lf.replace(SPECTRUM_IRND0, SPECTRUM_FCLOSE, 1)
        n += 1
    if n == 0:
        return text, 0
    if _nl(text) == "\r\n":
        lf = lf.replace("\n", "\r\n")
    return lf, n


def _adapt(snippet: str, nl: str) -> str:
    return snippet.replace("\r\n", "\n").replace("\n", nl)


def apply_route_a(text: str) -> tuple[str, str]:
    """Return (new_text, status) where status is 'applied', 'already', or raises."""
    nl = _nl(text)
    if MARKER in text:
        if "=== Route A: per-beam tally reset ===" in text:
            text, n_close = _ensure_fclose(text)
            return text, "already" if n_close == 0 else "fclose"
        needle = "    argv[1] = routeA_beam_files[routeA_beam];"
        if needle not in text:
            raise ValueError("Route A loop is present but argv[1] assignment was not found")
        extra = _adapt(
            "\n    // === Route A: per-beam tally reset ===\n"
            "    // Each beam writes its own dose file. Accumulating into one tally would\n"
            "    // collapse the unequal Omega_k weights (MC_SOURCE_MODEL.md 5.3.0e).\n"
            "    time_total_MC_simulation = 0.0;\n"
            "    time_elapsed_MC_loop = 0.0;\n"
            "    for(kk=0;kk<MAX_MATERIALS;kk++)\n"
            "    {\n"
            "      materials_dose[kk].x = 0;\n"
            "      materials_dose[kk].y = 0;\n"
            "    }\n",
            nl,
        )
        text = text.replace(needle, needle + extra, 1)
        text, _ = _ensure_fclose(text)
        return text, "tally-reset"

    if DECL not in text:
        raise ValueError("anchor not found: file_name_espc declaration")
    if READ_INPUT not in text:
        raise ValueError("anchor not found: read_input comment")
    if CLEAN_ENDIF not in text.replace("\r\n", "\n"):
        raise ValueError("anchor not found: host cleanup / MPI_Finalize")
    if LOAD_OPEN not in text.replace("\r\n", "\n"):
        raise ValueError("anchor not found: load_voxels open")
    if LOAD_CLOSE not in text.replace("\r\n", "\n"):
        raise ValueError("anchor not found: load_voxels close")

    # Work in LF, restore file newlines at the end of each insertion via _adapt.
    lf = text.replace("\r\n", "\n")
    loop_start = LOOP_START.replace("\r\n", "\n")
    loop_end = LOOP_END.replace("\r\n", "\n")
    head = LOAD_CACHE_HEAD.replace("\r\n", "\n")
    tail = LOAD_CACHE_TAIL.replace("\r\n", "\n")

    lf = lf.replace(DECL + "\n\n" + READ_INPUT, DECL + "\n" + loop_start + READ_INPUT, 1)
    lf = lf.replace(CLEAN_ENDIF, "#endif\n" + loop_end + "\n#ifdef USING_MPI\n  MPI_Finalize();   // Finalize MPI library: no more MPI calls allowed below.", 1)
    lf = lf.replace(LOAD_OPEN, "  char *new_line_ptr = NULL;  \n" + head + "  MASTER_THREAD if (strstr(file_name_voxels,\".zip\")!=NULL)", 1)
    lf = lf.replace(LOAD_CLOSE, LOAD_CLOSE[:-1] + tail + "\n}", 1)

    if MARKER not in lf:
        raise ValueError("Route A loop start did not apply")
    if "reusing cached voxel geometry" not in lf:
        raise ValueError("load_voxels memo did not apply")
    if "end of the per-beam loop" not in lf:
        raise ValueError("Route A loop end did not apply")

    if nl == "\r\n":
        lf = lf.replace("\n", "\r\n")
    lf, _ = _ensure_fclose(lf)
    return lf, "applied"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: apply_route_a.py <MC-GPU_v1.3_win_{cpu,gpu}.cu>", file=sys.stderr)
        return 2
    path = Path(args[0])
    original = path.read_text(encoding="latin-1")
    updated, status = apply_route_a(original)
    if updated != original:
        path.write_text(updated, encoding="latin-1", newline="")
    print(f"[apply_route_a] {path.name}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
