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
    [string]$Arch = 'sm_86'   # RTX 3080 = GA102 = compute capability 8.6
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
       why = 'binary image file opened in text mode corrupts the .raw output on Windows' },
    @{ from = 'fopen(file_binary_mean, "w")'; to = 'fopen(file_binary_mean, "wb")';
       why = 'binary dose file opened in text mode corrupts the .raw output on Windows' },
    @{ from = 'fopen(file_binary_sigma, "w")'; to = 'fopen(file_binary_sigma, "wb")';
       why = 'binary dose-uncertainty file opened in text mode corrupts the .raw output on Windows' }
)
if ($Target -eq 'gpu') {
    $patches += @{ from = 'cudaThreadSynchronize'; to = 'cudaDeviceSynchronize';
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
    $applied += [ordered]@{ from = $p.from; to = $p.to; occurrences = $count; reason = $p.why }
}
Set-Content -Path $src -Value $text -Encoding ascii -NoNewline

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
        "/I`"$mcgpu`"", "/I`"$zlib`""
    )
    $line = 'cl ' + ($flags -join ' ') + " `"$src`" " + ($zsrc -join ' ') + " /Fe`"$exe`""
    $compiler = 'MSVC cl.exe (/TC /O2 /std:c17)'
}
else {
    if (-not $CudaSamples) { throw '-CudaSamples <path to a clone of github.com/NVIDIA/cuda-samples> is required for the gpu target' }
    $common = Join-Path $CudaSamples 'Common'
    if (-not (Test-Path (Join-Path $common 'helper_cuda.h'))) { throw "helper_cuda.h not found under $common" }
    $exe = Join-Path $build 'MC-GPU_v1.3_GPU.exe'
    $cc = ($Arch -replace 'sm_', '')
    $flags = @(
        '-O3', '-use_fast_math', '-m64', '-DUSING_CUDA',
        '-D_CRT_SECURE_NO_WARNINGS', '-D_USE_MATH_DEFINES',
        "-I`"$mcgpu`"", "-I`"$zlib`"", "-I`"$common`"",
        "-gencode=arch=compute_$cc,code=$Arch"
    )
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
$meta = [ordered]@{
    engine            = 'MC-GPU v1.3 (DIDSR/FDA, Andreu Badal) -- public domain'
    engine_source     = 'https://github.com/DIDSR/MCGPU'
    target            = $Target
    executable        = $exe
    executable_sha256 = (Get-FileHash $exe -Algorithm SHA256).Hash
    source_sha256     = (Get-FileHash (Join-Path $mcgpu 'MC-GPU_v1.3.cu') -Algorithm SHA256).Hash
    patched_source    = $src
    patched_sha256    = (Get-FileHash $src -Algorithm SHA256).Hash
    patches           = $applied
    compiler          = $compiler
    vs_installation   = $vsPath
    zlib              = 'zlib 1.3.1 (madler/zlib, zlib licence), statically compiled in'
}
$metaPath = Join-Path $build 'build_info.json'
$meta | ConvertTo-Json -Depth 4 | Set-Content -Path $metaPath -Encoding utf8
Write-Host "[build_mcgpu] ok  sha256=$($meta.executable_sha256)"
Write-Host "[build_mcgpu] wrote $metaPath"
