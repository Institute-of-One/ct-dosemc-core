"""The engine file formats.

MC-GPU's parser matches section headers literally and reads fields positionally,
so a reworded comment is harmless but a reordered line is not.  These tests pin
the things the engine actually depends on -- above all the aperture line, whose
documented order and real order disagree.
"""

from __future__ import annotations

import gzip

import numpy as np
import pytest

from ct_dosemc_core.mcgpu_io import write_input_file, write_voxel_file
from ct_dosemc_core.phantom import Material, VoxelPhantom

AIR = Material(1, "air", "air.mcgpu.gz", 1.20479e-3)
PMMA = Material(2, "PMMA", "PMMA.mcgpu.gz", 1.19)


def _phantom(nz=3, ny=4, nx=5):
    mat = np.full((nz, ny, nx), AIR.index, dtype=np.int16)
    mat[1, 1:3, 1:4] = PMMA.index
    dens = np.where(mat == PMMA.index, 1.19, 1.20479e-3)
    return VoxelPhantom(mat, dens, (0.2, 0.3, 0.4), (AIR, PMMA))


def _input(tmp_path, **overrides):
    kw = dict(
        histories_per_projection=1.0e6,
        random_seed=42,
        spectrum_file="spectrum.spc",
        source_position_cm=(18.0, -42.0, 9.5),
        source_direction=(0.0, 1.0, 0.0),
        polar_aperture_deg=1.9096,
        azimuthal_aperture_deg=32.9320,
        image_file="image.dat",
        image_pixels=(8, 8),
        image_size_cm=(59.0, 3.2),
        sdd_cm=100.0,
        n_projections=180,
        angle_between_projections_deg=2.0,
        sad_cm=60.0,
        translation_per_projection_cm=0.0,
        dose_file="dose.dat",
        voxel_file="phantom.vox.gz",
        materials=(AIR, PMMA),
        dose_roi=((1, 144), (1, 144), (1, 76)),
    )
    kw.update(overrides)
    return write_input_file(tmp_path / "ctdi.in", **kw).read_text(encoding="ascii")


# -- voxel file -------------------------------------------------------------


def test_voxel_file_header_matches_the_penEasy_format(tmp_path):
    ph = _phantom()
    path = write_voxel_file(tmp_path / "p.vox.gz", ph)
    with gzip.open(path, "rt", encoding="ascii") as fh:
        text = fh.read()
    head, body = text.split("[END OF VXH SECTION]\n")
    assert "[SECTION VOXELS HEADER v.2008-04-13]" in head
    nx, ny, nz = ph.n_voxels
    assert f"{nx} {ny} {nz}" in head
    assert len(body.strip().splitlines()) == nx * ny * nz


def test_voxel_file_writes_x_fastest_then_y_then_z(tmp_path):
    ph = _phantom()
    path = write_voxel_file(tmp_path / "p.vox.gz", ph)
    with gzip.open(path, "rt", encoding="ascii") as fh:
        body = fh.read().split("[END OF VXH SECTION]\n")[1]
    mats = np.array([int(line.split()[0]) for line in body.strip().splitlines()])
    assert np.array_equal(mats, ph.material.reshape(-1))


def test_voxel_file_round_trips_material_and_density(tmp_path):
    ph = _phantom()
    path = write_voxel_file(tmp_path / "p.vox.gz", ph)
    with gzip.open(path, "rt", encoding="ascii") as fh:
        body = fh.read().split("[END OF VXH SECTION]\n")[1]
    rows = np.array([[float(v) for v in line.split()] for line in body.strip().splitlines()])
    assert np.array_equal(rows[:, 0].astype(int), ph.material.reshape(-1))
    np.testing.assert_allclose(rows[:, 1], ph.density.reshape(-1), rtol=1e-5)


def test_voxel_density_may_never_be_zero():
    mat = np.ones((2, 2, 2), dtype=np.int16)
    dens = np.zeros((2, 2, 2))
    with pytest.raises(ValueError, match="zero or negative voxel density"):
        VoxelPhantom(mat, dens, (1.0, 1.0, 1.0), (AIR,))


def test_more_materials_than_the_engine_supports_is_an_error():
    mat = np.ones((2, 2, 2), dtype=np.int16)
    dens = np.ones((2, 2, 2))
    many = tuple(Material(i + 1, f"m{i}", f"m{i}.gz", 1.0) for i in range(16))
    with pytest.raises(ValueError, match="MAX_MATERIALS"):
        VoxelPhantom(mat, dens, (1.0, 1.0, 1.0), many)


# -- input file -------------------------------------------------------------


@pytest.mark.parametrize(
    "header",
    [
        "SECTION SIMULATION CONFIG v.2009-05-12",
        "SECTION SOURCE v.2011-07-12",
        "SECTION IMAGE DETECTOR v.2009-12-02",
        "SECTION CT SCAN TRAJECTORY v.2011-10-25",
        "SECTION DOSE DEPOSITION v.2012-12-12",
        "SECTION VOXELIZED GEOMETRY FILE v.2009-11-30",
        "SECTION MATERIAL FILE LIST v.2009-11-30",
    ],
)
def test_every_section_header_the_parser_searches_for_is_present(tmp_path, header):
    assert header in _input(tmp_path)


def test_aperture_line_is_azimuthal_then_polar(tmp_path):
    """MC-GPU reads ``sscanf(line, "%lf %lf", &phi_aperture, &theta_aperture)``.

    Its own sample files label this line "POLAR AND AZIMUTHAL", which is
    backwards.  Writing them in the documented order gives a beam collimated
    across the fan and wide open along Z -- a simulation that runs happily and
    reports nonsense.
    """
    text = _input(tmp_path, azimuthal_aperture_deg=32.9320, polar_aperture_deg=1.9096)
    line = next(line for line in text.splitlines() if "APERTURES" in line)
    first, second = (float(v) for v in line.split("#")[0].split()[:2])
    assert first == pytest.approx(32.9320)
    assert second == pytest.approx(1.9096)


def test_materials_are_listed_in_index_order(tmp_path):
    text = _input(tmp_path, materials=(PMMA, AIR))
    body = text.split("SECTION MATERIAL FILE LIST v.2009-11-30")[1]
    files = [line.split()[0] for line in body.strip().splitlines() if line.strip().endswith(")")
             or ".gz" in line]
    assert files[:2] == ["air.mcgpu.gz", "PMMA.mcgpu.gz"]


def test_dose_roi_is_written_one_based(tmp_path):
    text = _input(tmp_path, dose_roi=((1, 144), (1, 144), (1, 76)))
    assert "1 144   # VOXEL DOSE ROI: X-index min max (first voxel has index 1)" in text
    assert "1 76   # VOXEL DOSE ROI: Z-index min max" in text


def test_histories_field_is_documented_as_per_projection(tmp_path):
    # MC-GPU divides the tally by total_histories * num_projections, so a reader
    # who takes this field for the whole scan is out by the projection count.
    text = _input(tmp_path)
    assert "PER PROJECTION" in text


def test_write_manifest_lists_one_input_per_line(tmp_path):
    from ct_dosemc_core.mcgpu_io import write_manifest

    path = write_manifest(tmp_path / "manifest.txt", ["a.in", "b.in"])
    lines = [
        ln
        for ln in path.read_text(encoding="ascii").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    assert lines == ["a.in", "b.in"]


def test_split_route_a_logs_isolates_per_beam_apertures(tmp_path):
    from ct_dosemc_core.mcgpu_io import split_route_a_logs

    batch = tmp_path / "mcgpu_batch.log"
    batch.write_text(
        "preamble\n"
        "========== [Route A] beam 1 / 2 : case4_g4_p000_fan00.in ==========\n"
        "      azimuthal (phi), polar apertures = 1.0 , 0.5 degrees\n"
        "========== [Route A] beam 2 / 2 : case4_g4_p000_fan01.in ==========\n"
        "      azimuthal (phi), polar apertures = 2.0 , 0.5 degrees\n",
        encoding="latin-1",
    )
    logs = split_route_a_logs(batch, tmp_path)
    assert set(logs) == {"case4_g4_p000_fan00.in", "case4_g4_p000_fan01.in"}
    t0 = logs["case4_g4_p000_fan00.in"].read_text(encoding="latin-1")
    t1 = logs["case4_g4_p000_fan01.in"].read_text(encoding="latin-1")
    assert "apertures = 1.0" in t0 and "apertures = 2.0" not in t0
    assert "apertures = 2.0" in t1 and "apertures = 1.0" not in t1
    assert logs["case4_g4_p000_fan00.in"].name == "mcgpu_g4_p000_fan00.log"

