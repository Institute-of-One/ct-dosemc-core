<#
    build_mcgpu.ps1 -- build the MC-GPU v1.3 transport engine on Windows.

    MC-GPU v1.3 (DIDSR/FDA, Andreu Badal) is in the PUBLIC DOMAIN.  It is vendored
    unmodified under vendor/MCGPU (see docs/MC_SOURCE_MODEL.md); this script only
    compiles it.  Upstream ships a Linux Makefile that assumes nvcc + gcc; this is
    the Windows/MSVC equivalent.

    Two targets:
      -Target cpu   sequential CPU build (no CUDA toolkit required).  This is the
                    reference build: identical physics, ~20-40x slower.
      -Target gpu   CUDA build for the local NVIDIA GPU.  Requires the CUDA
                    toolkit (nvcc) plus the cuda-samples "Common" headers
                    (helper_cuda.h / helper_functions.h), which NVIDIA removed
                    from the toolkit after CUDA 11.  Point -CudaSamples at a
                    clone of github.com/NVIDIA/cuda-samples.

    zlib (madler/zlib, zlib licence) is compiled in from vendor/zlib-1.3.1 because
    MC-GPU includes zlib.h to read gzip-ed material/voxel files.

    Usage:
      powershell -File tools/build_mcgpu.ps1 -Target cpu
      powershell -File tools/build_mcgpu.ps1 -Target gpu -CudaSamples D:\src\cuda-samples
#>
[CmdletBinding()]
param(
    [ValidateSet('cpu', 'gpu')]
    [string]$Target = 'cpu',
    [string]$CudaSamples = '',
    [string]$Arch = 'sm_86',  # RTX 3080 = GA102 = compute capability 8.6
    [string]$CcBin = '',      # host compiler for nvcc, e.g. a VS 2022 v143 cl.exe
    [string]$CudaPath = ''    # a CUDA tree (bin/include/lib); no admin install needed
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$mcgpu = Join-Path $repo 'vendor\MCGPU'
$zlib = Join-Path $repo 'vendor\zlib-1.3.1'
$build = Join-Path $repo 'vendor\build'

foreach ($p in @($mcgpu, $zlib)) {
    if (-not (Test-Path $p)) { throw "missing vendored source: $p (see docs/MC_SOURCE_MODEL.md)" }
}
New-Item -ItemType Directory -Force -Path $build | Out-Null

# -- locate the MSVC toolset ------------------------------------------------
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path $vswhere)) { throw 'vswhere.exe not found; install Visual Studio Build Tools with the C++ workload' }
$vsPath = (& $vswhere -latest -products '*' -property installationPath) | Select-Object -First 1
$vcvars = Join-Path $vsPath 'VC\Auxiliary\Build\vcvars64.bat'
if (-not (Test-Path $vcvars)) { throw "vcvars64.bat not found under $vsPath" }

$zsrc = @(
    'adler32.c', 'compress.c', 'crc32.c', 'deflate.c', 'gzclose.c', 'gzlib.c',
    'gzread.c', 'gzwrite.c', 'infback.c', 'inffast.c', 'inflate.c', 'inftrees.c',
    'trees.c', 'uncompr.c', 'zutil.c'
) | ForEach-Object { '"' + (Join-Path $zlib $_) + '"' }

# -- Windows portability patches, applied to a COPY -------------------------
# vendor/MCGPU stays byte-identical to upstream; every substitution below is
# recorded in build_info.json and documented in docs/MC_SOURCE_MODEL.md.
#
#  1. The three output files marked "!!BINARY!!" in the upstream source are
#     opened with fopen(..., "w").  On Linux that is exactly "wb"; on Windows
#     the CRT translates every 0x0A byte in the 32-bit floats to 0x0D 0x0A,
#     which silently corrupts the dose tally and the projection images.  Every
#     value read back is garbage, so this is a correctness fix, not cosmetics.
#  2. cudaThreadSynchronize() was removed in CUDA 12 (gpu target only).
$patches = @(
    @{ from = 'fopen(file_binary, "w")'; to = 'fopen(file_binary, "wb")';
       kind = 'defect_fix'; upstream = 'DIDSR/MCGPU#24';
       why = 'binary image file opened in text mode corrupts the .raw output on Windows' },
    @{ from = 'fopen(file_binary_mean, "w")'; to = 'fopen(file_binary_mean, "wb")';
       kind = 'defect_fix'; upstream = 'DIDSR/MCGPU#24';
       why = 'binary dose file opened in text mode corrupts the .raw output on Windows' },
    @{ from = 'fopen(file_binary_sigma, "w")'; to = 'fopen(file_binary_sigma, "wb")';
       kind = 'defect_fix'; upstream = 'DIDSR/MCGPU#24';
       why = 'binary dose-uncertainty file opened in text mode corrupts the .raw output on Windows' },
    #  The pencil-beam guard calls abs() on a double.  In C that is
    #  <stdlib.h>'s int abs(int), so the argument is truncated: EVERY aperture
    #  smaller than 1 degree tests as zero and is silently replaced by a pencil
    #  beam.  A 10 mm collimation at 600 mm SAD is 0.95 degrees, so a perfectly
    #  ordinary CT beam vanishes.  Only the CPU build is affected -- nvcc
    #  compiles .cu as C++, where abs() has a double overload -- which is why it
    #  has survived in the build upstream documents as "gcc -x c".
    @{ from = 'if (abs(theta_aperture) < 1.0e-7)'; to = 'if (fabs(theta_aperture) < 1.0e-7)';
       kind = 'defect_fix'; upstream = 'DIDSR/MCGPU#22';
       why = 'abs() on a double truncates to int in C: polar apertures below 1 deg became pencil beams' },
    @{ from = 'if (abs(phi_aperture) < 1.0e-7)'; to = 'if (fabs(phi_aperture) < 1.0e-7)';
       kind = 'defect_fix'; upstream = 'DIDSR/MCGPU#22';
       why = 'abs() on a double truncates to int in C: azimuthal apertures below 1 deg became pencil beams' }
)
if ($Target -eq 'gpu') {
    $patches += @{ from = 'cudaThreadSynchronize'; to = 'cudaDeviceSynchronize';
                   kind = 'portability'; upstream = $null;
                   why = 'removed from the CUDA runtime in CUDA 12' }
}
else {
    #  3. The CUDA branch advances the PRNG seed between projections
    #     ("update_seed_PRNG(numprocs, total_histories, &seed_input)", upstream
    #     line 869) but that call sits inside #ifdef USING_CUDA, so the CPU
    #     branch replays the identical random sequence for every projection.  In
    #     a CT trajectory that makes the projections perfectly correlated: the
    #     tally comes out exactly symmetric under the rotation step and the
    #     reported statistical uncertainty is meaningless.  init_PRNG leaps ahead
    #     by (history_batch+1)*histories_per_thread*LEAP_DISTANCE
    #     (MC-GPU_kernel_v1.3.cu:841-847), so offsetting the batch index by one
    #     whole projection's worth of batches gives each projection a disjoint
    #     stretch of the sequence -- the same guarantee the CUDA branch has.
    $patches += @{
        from = 'track_particles(CPU_batch, histories_per_thread, num_p, seed_input, image,'
        to   = 'track_particles(CPU_batch + num_p*total_threads, histories_per_thread, num_p, seed_input, image,'
        kind = 'defect_fix'; upstream = 'DIDSR/MCGPU#23';
        why  = 'CPU branch reused one random sequence for every projection; offset the PRNG batch index per projection'
    }
}

$src = Join-Path $build "MC-GPU_v1.3_win_$Target.cu"
$text = Get-Content (Join-Path $mcgpu 'MC-GPU_v1.3.cu') -Raw
$applied = @()
foreach ($p in $patches) {
    $count = ([regex]::Matches($text, [regex]::Escape($p.from))).Count
    if ($count -eq 0) { throw "patch target not found in upstream source: $($p.from)" }
    $text = $text.Replace($p.from, $p.to)
    $applied += [ordered]@{
        kind = $p.kind
        upstream = $p.upstream
        from = $p.from
        to = $p.to
        occurrences = $count
        reason = $p.why
    }
}
Set-Content -Path $src -Value $text -Encoding ascii -NoNewline

# Capacity: Schneider soft+cortical bone mixes emit up to 32 Compton shells
# (bone_4..bone_11). Upstream MAX_SHELLS=30 is enough for TG-195 PMMA/air
# (4 and 9 shells) and for ICRP soft tissue (30), but not for the mixes.
# Array bound only; Compton sampling still loops noscco[mat]. Not a defect
# fix and not a physics change. Applied to a COPY of the header in vendor/build
# so vendor/MCGPU stays byte-identical to upstream.
$headerSrc = Join-Path $mcgpu 'MC-GPU_v1.3.h'
$headerDst = Join-Path $build 'MC-GPU_v1.3.h'
$header = Get-Content $headerSrc -Raw
$shellFrom = '#define  MAX_SHELLS         30'
$shellTo   = '#define  MAX_SHELLS         40'
$binsFrom  = '#define  MAX_ENERGYBINS_RAYLEIGH  25005'
$binsTo    = '#define  MAX_ENERGYBINS_RAYLEIGH  32000'
if ($header -notlike "*$shellFrom*") { throw "MAX_SHELLS patch target not found in $headerSrc" }
if ($header -notlike "*$binsFrom*") { throw "MAX_ENERGYBINS_RAYLEIGH patch target not found in $headerSrc" }
$header = $header.Replace($shellFrom, $shellTo).Replace($binsFrom, $binsTo)
Set-Content -Path $headerDst -Value $header -Encoding ascii -NoNewline
$applied += [ordered]@{
    kind = 'capacity'
    upstream = $null
    from = $shellFrom
    to = $shellTo
    occurrences = 1
    reason = 'Schneider soft+cortical bone mixes emit up to 32 Compton shells; upstream MAX_SHELLS=30 is enough for TG-195 PMMA/air. Array bound only; sampling still loops noscco[mat].'
}
$applied += [ordered]@{
    kind = 'capacity'
    upstream = $null
    from = $binsFrom
    to = $binsTo
    occurrences = 1
    reason = '5-150 keV Schneider tables at 5 eV step have 29002 Rayleigh bins; upstream MAX_ENERGYBINS_RAYLEIGH=25005 fits 5-120 keV (23001 bins) only. Array bound only; same 5 eV grid. Do not coarsen the 140 kVp tables.'
}

# Route A (@manifest + load_voxels memo) is the same C on both targets, so G5
# keeps comparing one definition. tools/apply_route_a.py is idempotent.
$py = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
& $py (Join-Path $PSScriptRoot 'apply_route_a.py') $src
if ($LASTEXITCODE -ne 0) { throw "apply_route_a.py failed on $src" }
# Route A is a performance modification, not a defect fix. It must not sit in
# patches[] next to #22-#26: a reviewer who sees "we modified the engine" will
# ask whether the physics changed. Answer: it did not (byte-equality vs Route B).
$performance = @([ordered]@{
    kind = 'performance'
    name = 'Route A batch mode (in-process sub-fan loop)'
    not_a_defect_fix = $true
    physics_unchanged = $true
    from = 'single input file (argv[1]); load_voxels re-parses every invocation'
    to = "argv[1]=='@manifest' runs every listed input file sequentially in one process; load_voxels memoises the parsed geometry by filename and hands each later beam a fresh copy"
    applied_to = @('MC-GPU_v1.3_win_cpu.cu', 'MC-GPU_v1.3_win_gpu.cu')
    identical_definition_both_targets = $true
    reason = 'hoist the ~58M-voxel ASCII parse out of the P*K sub-fan loop. Transport, RNG and per-beam tallies are unchanged. An equal-weight single-tally sum would bias the estimator by -0.53%; each beam still writes its own dose file. Route A also fclose()s the input and spectrum FILE* per beam: a standalone process exits, but a 2016-beam z-station manifest hits the MSVC 512-handle cap around beam 255.'
    validation = 'byte-equality, not within-statistics: on the GPU L40 10-replica Route B reference, a same-seed Route A replica matches all 144 dose .raw SHA-256 and the scored VOI values are bit-identical (results/phase1a/replica_120kvp_second_K4_L40_00_routeA).'
})

if ($Target -eq 'cpu') {
    $exe = Join-Path $build 'MC-GPU_v1.3_CPU.exe'
    # /TC            : the .cu file is plain C in the non-CUDA path
    # /std:c17       : MC-GPU uses C99 declarations
    # /Dinline=static: C99 "inline" with no external definition leaves the kernel
    #                  helpers unresolved at link time under MSVC; upstream relies on
    #                  gcc -O3 always inlining them.  "static" restores the intended
    #                  single-translation-unit semantics without editing the source.
    # /F 512MB: MC-GPU declares the per-projection source and detector arrays, the
    # material MFP tables and the Rayleigh/Compton blocks as automatic storage.  On
    # Linux the default stack grows; MSVC's 1 MB default overflows before the first
    # history is tracked (exit 0xC00000FD).
    $flags = @(
        '/nologo', '/TC', '/O2', '/fp:fast', '/std:c17', '/wd4996',
        '/D_CRT_SECURE_NO_WARNINGS', '/D_USE_MATH_DEFINES', '/Dinline=static',
        '/F', '536870912',
        "/I`"$build`"", "/I`"$mcgpu`"", "/I`"$zlib`""
    )
    $line = 'cl ' + ($flags -join ' ') + " `"$src`" " + ($zsrc -join ' ') + " /Fe`"$exe`""
    $compiler = 'MSVC cl.exe (/TC /O2 /std:c17)'
}
else {
    # CUDA 12.4 or 12.6 is recommended over 13.x: this is 2012 code, and the older
    # toolkits are far more tolerant of it.  A driver that reports CUDA 13.2
    # support runs 12.x binaries without trouble.
    #
    # cuda-samples must be cloned at the SAME tag as the toolkit -- the Common
    # headers track the runtime API and a mismatched pair fails in confusing ways:
    #   git clone --branch v12.4 --depth 1 https://github.com/NVIDIA/cuda-samples
    #
    # If nvcc rejects the MSVC version (Visual Studio 18 BuildTools is newer than
    # any 12.x toolkit knows about), try -allow-unsupported-compiler first; if the
    # build then fails inside the CRT headers, install the VS 2022 v143 toolset
    # side by side and point nvcc at it with -ccbin.
    if (-not $CudaSamples) { throw '-CudaSamples <path to a clone of github.com/NVIDIA/cuda-samples, same tag as the toolkit> is required for the gpu target' }
    $common = Join-Path $CudaSamples 'Common'
    if (-not (Test-Path (Join-Path $common 'helper_cuda.h'))) { throw "helper_cuda.h not found under $common" }
    # A full administrator install is not the only way to get nvcc. A merged
    # redistributable tree (bin/include/lib) works, and can come from the NVIDIA
    # redist archives, from conda's nvidia channel, or from an existing tree
    # already on the machine. -CudaPath points at one.
    if ($CudaPath) {
        if (-not (Test-Path (Join-Path $CudaPath 'bin/nvcc.exe'))) { throw "no bin/nvcc.exe under $CudaPath" }
        $env:PATH = (Join-Path $CudaPath 'bin') + ';' + $env:PATH
        $env:CUDA_PATH = $CudaPath
    }
    if (-not (Get-Command nvcc -ErrorAction SilentlyContinue)) {
        throw 'nvcc is not on PATH and -CudaPath was not given. Note the pip distribution ships only ptxas on Windows; use the NVIDIA redist archives or conda -c nvidia cuda-nvcc.'
    }
    $nvccVersion = ((& nvcc --version) | Select-String 'release' | Out-String).Trim()
    $exe = Join-Path $build 'MC-GPU_v1.3_GPU.exe'
    $cc = ($Arch -replace 'sm_', '')
    $flags = @(
        '-O3', '-use_fast_math', '-m64', '-DUSING_CUDA',
        '-D_CRT_SECURE_NO_WARNINGS', '-D_USE_MATH_DEFINES',
        '-allow-unsupported-compiler',
        # Same 512 MB stack the CPU target needs, and for the same reason: the
        # per-projection source/detector arrays and the material tables are
        # automatic storage on the host side.  MSVC's 1 MB default overflows
        # before the first history (0xC00000FD).  nvcc has to pass it through to
        # the host linker rather than handling it itself.
        '-Xlinker', '/STACK:536870912',
        "-I`"$build`"", "-I`"$mcgpu`"", "-I`"$zlib`"", "-I`"$common`"",
        "-gencode=arch=compute_$cc,code=$Arch"
    )
    if ($CudaPath) {
        $flags += "-I`"$(Join-Path $CudaPath 'include')`""
        $flags += "-L`"$(Join-Path $CudaPath 'lib/x64')`""
    }
    $flags += '-lcudart'
    if ($CcBin) { $flags += "-ccbin `"$CcBin`"" }
    $line = 'nvcc ' + ($flags -join ' ') + " `"$src`" " + ($zsrc -join ' ') + " -o `"$exe`""
    $compiler = "nvcc -> $Arch (host: MSVC)"
}

# Run through a generated .bat: vcvars64 must run in the same cmd session, and this
# avoids PowerShell/cmd quote mangling on the long compiler line.
$bat = Join-Path $build "_build_$Target.bat"
@(
    '@echo off',
    "call `"$vcvars`" >nul || exit /b 1",
    "cd /d `"$build`"",
    $line
) | Set-Content -Path $bat -Encoding ascii

Write-Host "[build_mcgpu] target=$Target -> $exe"
if (Test-Path $exe) { Remove-Item $exe -Force }
cmd.exe /c "`"$bat`""
if (-not (Test-Path $exe)) { throw "compilation failed: $exe was not produced (see output above)" }

# record what was built, so provenance can quote it
$builtUtc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
$thisTarget = [ordered]@{
    executable        = $exe
    executable_sha256 = (Get-FileHash $exe -Algorithm SHA256).Hash
    patched_source    = $src
    patched_sha256    = (Get-FileHash $src -Algorithm SHA256).Hash
    compiler          = $compiler
    built_utc         = $builtUtc
}
if ($Target -eq 'gpu') {
    $thisTarget.cuda_version = $nvccVersion
    $thisTarget.cuda_path = $CudaPath
    $thisTarget.cuda_samples = $CudaSamples
}

$metaPath = Join-Path $build 'build_info.json'
$targets = [ordered]@{}
if (Test-Path $metaPath) {
    $prev = Get-Content $metaPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($prev.targets) {
        foreach ($name in @('cpu', 'gpu')) {
            if ($prev.targets.$name) {
                $targets[$name] = $prev.targets.$name
            }
        }
    }
    elseif ($prev.target -and $prev.target -ne $Target) {
        $targets[$prev.target] = [ordered]@{
            executable        = $prev.executable
            executable_sha256 = $prev.executable_sha256
            patched_source    = $prev.patched_source
            patched_sha256    = $prev.patched_sha256
            compiler          = $prev.compiler
        }
    }
}
$targets[$Target] = $thisTarget

# Production numbers are GPU. Keep that as the top-level record when both exist
# so a CPU rebuild does not look like the cited executable changed.
$prod = if ($targets['gpu']) { 'gpu' } else { $Target }
$prodInfo = $targets[$prod]

$meta = [ordered]@{
    engine            = 'MC-GPU v1.3 (DIDSR/FDA, Andreu Badal) -- public domain'
    engine_source     = 'https://github.com/DIDSR/MCGPU'
    source_sha256     = (Get-FileHash (Join-Path $mcgpu 'MC-GPU_v1.3.cu') -Algorithm SHA256).Hash
    patch_kinds       = 'patches[] are defect_fix, portability (#22-#24, CUDA 12), or capacity (MAX_SHELLS, MAX_ENERGYBINS_RAYLEIGH). performance_modifications[] are not defect fixes and change no physics.'
    patches           = $applied
    performance_modifications = $performance
    targets           = $targets
    target            = $prod
    executable        = $prodInfo.executable
    executable_sha256 = $prodInfo.executable_sha256
    patched_source    = $prodInfo.patched_source
    patched_sha256    = $prodInfo.patched_sha256
    compiler          = $prodInfo.compiler
    cuda_version      = $nvccVersion
    cuda_path         = $CudaPath
    cuda_samples      = $CudaSamples
    vs_installation   = $vsPath
    zlib              = 'zlib 1.3.1 (madler/zlib, zlib licence), statically compiled in'
}
$meta | ConvertTo-Json -Depth 6 | Set-Content -Path $metaPath -Encoding utf8
Write-Host "[build_mcgpu] ok  sha256=$($meta.executable_sha256)"
Write-Host "[build_mcgpu] wrote $metaPath"
