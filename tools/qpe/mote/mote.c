/*
 * mote.c: the Mote pipeline (oh4_halftone.h, Eric Scrivner, public domain; the library behind
 * https://mote.oh4.co) as one call, for the Mote editor of the qpe viewer. qpe.py builds it into
 * tools/qpe/out/libmote.{dylib,so} and calls mote_run through ctypes.
 *
 * Steps, as on mote.oh4.co: grayscale -> lift/gain/contrast/gamma -> invert -> sharpen -> edges ->
 * ordered threshold bias + error diffusion. oh4_halftone.h is used unchanged.
 *
 * Added for qpe: 4 levels (black, dark grey, light grey, white; p[P_LEVELS] = 4) instead of 1 bit.
 * dither_levels is HT_DitherBiased with the threshold, the ordered bias and the error taken
 * between the two levels a pixel lies between; with 2 levels HT_DitherBiased itself is used.
 */
#define OH4_HALFTONE_IMPLEMENTATION
#include "oh4_halftone.h"

#include <stdlib.h>
#include <string.h>

/* p[]: the editor's settings, in this order */
enum {
	P_GRAY, P_WR, P_WG, P_WB,                       /* gray mode 0 BT.601, 1 BT.709, 2 average, 3 custom weights */
	P_LIFT, P_GAIN, P_CONTRAST, P_GAMMA, P_THRESHOLD, P_INVERT,
	P_SHARPEN, P_RADIUS,
	P_EDGE, P_EDGE_STRENGTH,                        /* edge 0 none, 1 Sobel, 2 Scharr, 3 Laplacian */
	P_ORDERED, P_BAYER, P_ORDERED_SCALE,            /* ordered 0 none, 1 Bayer (size 0..4: 2..32), 2 blue noise,
	                                                   3 white noise, 4 IGN, 5 halftone, 6 diagonal, 7 h-line,
	                                                   8 v-line */
	P_DIFFUSION, P_DIFFUSION_STRENGTH, P_SERPENTINE, /* diffusion: eHT_Method */
	P_LEVELS, P_DARK, P_LIGHT,                      /* 2 or 4 levels; the grey levels (0..255) with 4 */
	P_COUNT
};

static unsigned int rng_state;
static int rng(void) {      /* fixed seed: the noise matrices, and so the result, are the same on every call */
	rng_state = rng_state * 1103515245u + 12345u;
	return (int)((rng_state >> 16) & 0x7fff);
}

static unsigned char blue[4096], white[4096], ign[4096];
static int have_blue, have_white, have_ign;

int mote_param_count(void) { return P_COUNT; }

/* HT_DitherBiased for n levels v[0] < ... < v[n-1]: out[i] = the level index. A pixel between v[k]
 * and v[k+1] is placed in that gap (t 0..1), shifted by the threshold and the ordered bias in
 * units of the gap (so each gap is dithered as Mote dithers 0..255), and the error is taken to
 * the level picked, as HT_DitherBiased does (ordered bias included). */
static void dither_levels(unsigned char* out, float* work, int w, int h, const float* v, int n,
                          eHT_Method method, const HT_Dither_Biased_Params* params) {
	ht__kernel* kernel = ht__kernel_from_method(method);
	int has_ordered = (params->OrderedMatrix || params->OrderedMatrixU16) && params->OrderedMax > 0.0f;
	float shift = (128.0f - params->Threshold) / 255.0f;
	int x, y, k;
	for (y = 0; y < h; y++) {
		int reverse = params->Serpentine && (y & 1);
		int x_start = reverse ? w - 1 : 0, x_end = reverse ? -1 : w, x_step = reverse ? -1 : 1;
		for (x = x_start; x != x_end; x += x_step) {
			int i = y * w + x, lv;
			float lum = work[i], gap, t, err;
			for (k = 0; k < n - 2 && lum > v[k + 1]; k++) {
			}
			gap = v[k + 1] - v[k];
			t = (lum - v[k]) / gap + shift;
			if (has_ordered) {
				int mi = (x % params->OrderedN) + (y % params->OrderedN) * params->OrderedN;
				float mv = params->OrderedMatrix ? (float)params->OrderedMatrix[mi] : (float)params->OrderedMatrixU16[mi];
				float bd = (mv / params->OrderedMax - 0.5f) * params->OrderedScale;
				t += bd;
				lum += bd * gap;
			}
			lv = t > 0.5f ? k + 1 : k;
			out[i] = (unsigned char)lv;
			if (kernel) {
				err = (lum - v[lv]) * params->DiffusionStrength;
				for (k = 0; k < kernel->count; k++) {
					int nx = x + (reverse ? -kernel->entries[k].dx : kernel->entries[k].dx);
					int ny = y + kernel->entries[k].dy;
					if (nx >= 0 && nx < w && ny >= 0 && ny < h) {
						work[ny * w + nx] += err * (float)kernel->entries[k].weight / (float)kernel->scale;
					}
				}
			}
		}
	}
}

/* rgba: w*h*4. bits: w*h bytes, the level: 0 black .. levels - 1 white (with 2 levels 1 = white).
 * Returns 0, or -1 when out of memory. */
int mote_run(unsigned char* rgba, int w, int h, const float* p, unsigned char* bits) {
	int n = w * h, i;
	float* gray = (float*)malloc(sizeof(float) * n);
	float* scratch = (float*)malloc(sizeof(float) * n);
	unsigned char* packed = (unsigned char*)calloc(HT_BilevelSize(w, h), 1);
	HT_Dither_Biased_Params dp;
	if (!gray || !scratch || !packed) {
		free(gray); free(scratch); free(packed);
		return -1;
	}

	if ((int)p[P_GRAY] == 3) {
		HT_GrayscaleFromRGBAWeightedF32(gray, rgba, w, h, p[P_WR], p[P_WG], p[P_WB]);
	} else {
		HT_GrayscaleFromRGBAF32(gray, rgba, w, h, (eHT_GrayMethod)(int)p[P_GRAY]);
	}
	HT_AdjustF32(gray, w, h, p[P_GAMMA], p[P_GAIN], p[P_CONTRAST], p[P_LIFT]);
	if (p[P_INVERT] != 0.0f) {
		for (i = 0; i < n; i++) {
			gray[i] = 255.0f - gray[i];
		}
	}
	HT_SharpenF32(gray, w, h, scratch, p[P_SHARPEN], (int)p[P_RADIUS]);
	if ((int)p[P_EDGE] > 0) {
		HT_EdgeDetectF32(scratch, gray, w, h, (eHT_EdgeMethod)((int)p[P_EDGE] - 1));
		HT_EdgeCompositeF32(gray, scratch, w, h, p[P_EDGE_STRENGTH]);
	}

	memset(&dp, 0, sizeof(dp));
	switch ((int)p[P_ORDERED]) {
		case 1: {
			int size = (int)p[P_BAYER];
			if (size >= 4) {
				dp.OrderedMatrixU16 = HT_BayerDefault32();
				dp.OrderedN = 32;
			} else {
				unsigned char* (*m[4])(void) = { HT_BayerDefault2, HT_BayerDefault4, HT_BayerDefault8, HT_BayerDefault16 };
				dp.OrderedMatrix = m[size < 0 ? 0 : size]();
				dp.OrderedN = 2 << (size < 0 ? 0 : size);
			}
			dp.OrderedMax = (float)(dp.OrderedN * dp.OrderedN);
		} break;
		case 2: {
			if (!have_blue) {
				float* bn = (float*)malloc(sizeof(float) * 12288);
				if (bn) {
					rng_state = 1;
					HT_BlueNoiseGenerate64(blue, bn, rng);
					free(bn);
					have_blue = 1;
				}
			}
			if (have_blue) { dp.OrderedMatrix = blue; dp.OrderedN = 64; dp.OrderedMax = 256.0f; }
		} break;
		case 3: {
			if (!have_white) { rng_state = 1; HT_WhiteNoiseGenerate64(white, rng); have_white = 1; }
			dp.OrderedMatrix = white; dp.OrderedN = 64; dp.OrderedMax = 256.0f;
		} break;
		case 4: {
			if (!have_ign) { HT_IGNGenerate64(ign); have_ign = 1; }
			dp.OrderedMatrix = ign; dp.OrderedN = 64; dp.OrderedMax = 256.0f;
		} break;
		case 5: dp.OrderedMatrix = HT_HalftoneDefault8();       dp.OrderedN = 8; dp.OrderedMax = 64.0f; break;
		case 6: dp.OrderedMatrix = HT_ClusteredDotDiagonal8();  dp.OrderedN = 8; dp.OrderedMax = 64.0f; break;
		case 7: dp.OrderedMatrix = HT_HorizontalLine6();        dp.OrderedN = 6; dp.OrderedMax = 36.0f; break;
		case 8: dp.OrderedMatrix = HT_VerticalLine6();          dp.OrderedN = 6; dp.OrderedMax = 36.0f; break;
		default: break;
	}
	dp.OrderedScale = p[P_ORDERED_SCALE];
	dp.Threshold = p[P_THRESHOLD];
	dp.Serpentine = p[P_SERPENTINE] != 0.0f;
	dp.DiffusionStrength = p[P_DIFFUSION_STRENGTH];
	if ((int)p[P_LEVELS] == 4) {
		float v[4];
		v[0] = 0.0f; v[3] = 255.0f;
		v[1] = p[P_DARK] < 1.0f ? 1.0f : p[P_DARK] > 253.0f ? 253.0f : p[P_DARK];
		v[2] = p[P_LIGHT] <= v[1] ? v[1] + 1.0f : p[P_LIGHT] > 254.0f ? 254.0f : p[P_LIGHT];
		dither_levels(bits, gray, w, h, v, 4, (eHT_Method)(int)p[P_DIFFUSION], &dp);
	} else {
		HT_DitherBiased(packed, 0, gray, 0, w, h, (eHT_Method)(int)p[P_DIFFUSION], &dp);
		for (i = 0; i < n; i++) {
			bits[i] = (packed[i >> 3] >> (7 - (i & 7))) & 1;
		}
	}
	free(gray); free(scratch); free(packed);
	return 0;
}
