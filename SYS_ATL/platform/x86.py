from __future__ import annotations

import sys

sys.path.append(sys.path[0] + "/..")
sys.path.append(sys.path[0] + "/.")

from SYS_ATL import instr, DRAM
from SYS_ATL.libs.memories import AVX2, AVX512


# --------------------------------------------------------------------------- #
#   AVX2 intrinsics
# --------------------------------------------------------------------------- #

@instr('{dst} = _mm256_loadu_ps({src}.data);')
def mm256_loadu_ps(
    dst: f32[8] @ AVX2,
    src: [f32][8] @ DRAM
):
    assert stride(src, 0) == 1
    assert stride(dst, 0) == 1

    for i in par(0, 8):
        dst[i] = src[i]


@instr('_mm256_storeu_ps({dst}.data, {src});')
def mm256_storeu_ps(
    dst: [f32][8] @ DRAM,
    src: f32[8] @ AVX2
):
    assert stride(src, 0) == 1
    assert stride(dst, 0) == 1

    for i in par(0, 8):
        dst[i] = src[i]


@instr('*(__m256*){dst}.data = '
       '_mm256_fmadd_ps({src1}, {src2}, *(__m256*){dst}.data);')
def mm256_fmadd_ps(
    dst: [f32][8] @ AVX2,
    src1: f32[8] @ AVX2,
    src2: f32[8] @ AVX2,
):
    assert stride(src1, 0) == 1
    assert stride(src2, 0) == 1
    assert stride(dst, 0) == 1

    for i in par(0, 8):
        dst[i] += src1[i] * src2[i]


@instr('{out} = _mm256_broadcast_ss({val}.data);')
def mm256_broadcast_ss(
    out: f32[8] @ AVX2,
    val: [f32][1],
):
    assert stride(out, 0) == 1

    for i in par(0, 8):
        out[i] = val[0]


@instr('{out} = _mm256_mul_ps({x}, {y});')
def mm256_mul_ps(
    out: f32[8] @ AVX2,
    x: f32[8] @ AVX2,
    y: f32[8] @ AVX2
):
    assert stride(out, 0) == 1
    assert stride(x, 0) == 1
    assert stride(y, 0) == 1

    for i in par(0, 8):
        out[i] = x[i] * y[i]


# --------------------------------------------------------------------------- #
#   AVX512 intrinsics
# --------------------------------------------------------------------------- #

@instr('{dst} = _mm512_loadu_ps({src}.data);')
def mm512_loadu_ps(
    dst: f32[16] @ AVX512,
    src: [f32][16] @ DRAM
):
    assert stride(src, 0) == 1
    assert stride(dst, 0) == 1

    for i in par(0, 16):
        dst[i] = src[i]


@instr('_mm512_storeu_ps({dst}.data, {src});')
def mm512_storeu_ps(
    dst: [f32][16] @ DRAM,
    src: f32[16] @ AVX512
):
    assert stride(dst, 0) == 1
    assert stride(src, 0) == 1

    for i in par(0, 16):
        dst[i] = src[i]


@instr('{dst} = _mm512_maskz_loadu_ps(((1 << {N}) - 1), {src}.data);')
def mm512_maskz_loadu_ps(
    N: size,
    dst: f32[16] @ AVX512,
    src: [f32][N] @ DRAM,
):
    assert stride(src, 0) == 1
    assert stride(dst, 0) == 1
    assert N <= 16

    for i in par(0, 16):
        if i < N:
            dst[i] = src[i]
        else:
            dst[i] = 0.0


@instr('_mm512_mask_storeu_ps({dst}.data, ((1 << {N}) - 1), {src});')
def mm512_mask_storeu_ps(
    N: size,
    dst: [f32][N] @ DRAM,
    src: f32[16] @ AVX512
):
    assert stride(src, 0) == 1
    assert stride(dst, 0) == 1
    assert N <= 16

    for i in par(0, 16):
        if i < N:
            dst[i] = src[i]


@instr('*(__m512*){C}.data = '
       '_mm512_fmadd_ps({A}, {B}, *(__m512*){C}.data);')
def mm512_fmadd_ps(
    A: f32[16] @ AVX512,
    B: f32[16] @ AVX512,
    C: [f32][16] @ AVX512,
):
    assert stride(A, 0) == 1
    assert stride(B, 0) == 1
    assert stride(C, 0) == 1

    for i in par(0, 16):
        C[i] += A[i] * B[i]


@instr('{dst} = _mm512_set1_ps({src});')
def mm512_set1_ps(
    dst: f32[16] @ AVX512,
    src: f32,
):
    assert stride(dst, 0) == 1

    for i in par(0, 16):
        dst[i] = src


# --------------------------------------------------------------------------- #
#   Compiler hints
# --------------------------------------------------------------------------- #

@instr('__builtin_unreachable();')
def unreachable():
    # assert False
    pass


# --------------------------------------------------------------------------- #
#   Complex AVX2 operations
# --------------------------------------------------------------------------- #

@instr('*(__m256*){out}.data = _mm256_xor_ps(*(__m256*){out}.data, '
       '*(__m256*){out}.data);')
def avx2_set0_ps(
    out: [f32][8] @ AVX2
):
    assert stride(out, 0) == 1

    for i in par(0, 8):
        out[i] = 0.0


@instr('''
{{
  __m256 ones = {{ 1.0f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f }};
  __m256 dst = _mm256_loadu_ps({dst}.data);
  _mm256_storeu_ps(
    {dst}.data,
    _mm256_fmadd_ps(ones, dst, *(__m256*){val}.data)
  );
}}
''')
def avx2_fmadd_memu_ps(
    dst: [f32][8] @ DRAM,
    val: [f32][8] @ AVX2
):
    assert stride(dst, 0) == 1
    assert stride(val, 0) == 1

    for i in par(0, 8):
        dst[i] += val[i]
