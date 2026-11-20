/*
	oh4_halftone.h - v1.1 - public domain
	Authored 2026 by Eric Scrivner
	no warranty implied; use at your own risk

	Before including,

		#define OH4_HALFTONE_IMPLEMENTATION

	in the file that you want to have the implementation.

ABOUT:

	Converts continuous-tone images to 1-bit (bilevel) output via grayscale
	conversion, tonal adjustment, sharpening, edge detection, and dithering.
	Output is packed MSB-first, 8 pixels per byte (Playdate bitmap format). Use
	HT_BilevelSize(w,h) for the required output buffer size.

	Based on potch's playdither tool (https://potch.me/demos/playdither/).

PIPELINE:

	All processing uses float, avoiding quantization loss between steps.

		HT_GrayscaleFromRGBAF32(out, rgba, w, h, method)
		HT_AdjustF32(buf, w, h, gamma, gain, contrast, lift)
		HT_SharpenF32(buf, w, h, scratch, amount, radius)
		HT_EdgeDetectF32(edge_out, grayscale, w, h, method)
		HT_EdgeCompositeF32(buf, edge, w, h, strength)
		HT_DitherBiased(out, mask, work, src_rgba, w, h, method, params)

	HT_DitherBiased combines an ordered dither matrix with error diffusion in a
	single pass. See HT_Dither_Biased_Params for configuration.  Pass
	kHT_Method_None to disable diffusion, or NULL matrix for to disable ordered
	dither.

ORDERED DITHER PATTERNS:

	Bayer       HT_BayerDefault2/4/8/16/32
	Blue noise  HT_BlueNoiseGenerate64
	Halftone    HT_HalftoneDefault8
	Diagonal    HT_ClusteredDotDiagonal8
	HLine       HT_HorizontalLine6
	VLine       HT_VerticalLine6
	White noise HT_WhiteNoiseGenerate64
	IGN         HT_IGNGenerate64

ERROR DIFFUSION METHODS (eHT_Method):

	Simple              1D forward (1/1)
	Box                 equal-weight 2x2
	Atkinson            partial diffusion (6/8)
	Burkes              two-row, wide spread
	Floyd-Steinberg     classic two-row (16ths)
	Jarvis-Judice-Ninke three-row, wide spread
	Pigeon              minimal forward-only
	Sierra Lite         simplified Sierra (4ths)
	Sierra 2            two-row Sierra
	Stucki              three-row, fine detail

SCRATCH BUFFERS:

	HT_SharpenF32, HT_EdgeDetectF32, and HT_DitherBiased each require a w*h
	float scratch buffer. HT_BlueNoiseGenerate64 requires 12288 floats (~48KB).

OVERRIDES:

	#define HT_Pow(x, e)   your_powf(x, e)
	#define HT_Exp(x)      your_expf(x)

EXAMPLE:

		#define W 400
		#define H 240
		float gray[W*H];
		float scratch[W*H];
		unsigned char bilevel[HT_BilevelSize(W,H)];
		unsigned char mask[HT_BilevelSize(W,H)];

		memset(bilevel, 0, sizeof(bilevel));
		memset(mask,    0, sizeof(mask));

		HT_GrayscaleFromRGBAF32(gray, rgba, W, H, kHT_GrayMethod_BT601);
		HT_AdjustF32(gray, W, H, 1.1f, 1.0f, 1.2f, 0.0f);
		HT_SharpenF32(gray, W, H, scratch, 0.5f, 1);

		unsigned char blue_noise[4096];
		float bn_scratch[12288];
		HT_BlueNoiseGenerate64(blue_noise, bn_scratch, my_rand);

		HT_Dither_Biased_Params params = {0};
		params.OrderedMatrix     = blue_noise;
		params.OrderedN          = 64;
		params.OrderedMax        = 255.0f;
		params.OrderedScale      = 0.3f;
		params.Threshold         = 128.0f;
		params.Serpentine        = 1;
		params.DiffusionStrength = 1.0f;
		HT_DitherBiased(bilevel, mask, gray, rgba, W, H, kHT_Method_FloydSteinberg, &params);

*/
#ifndef OH4_HALFTONE_H
#define OH4_HALFTONE_H

#ifndef HT_DEF
	#ifdef OH4_HALFTONE_STATIC
		#define HT_DEF static
	#else
		#ifdef __cplusplus
			#define HT_DEF extern "C"
		#else
			#define HT_DEF extern
		#endif
	#endif
#endif

/* === Constants === */

#define kHT_Grayscale_BT601_R	0.299f
#define kHT_Grayscale_BT601_G	0.587f
#define kHT_Grayscale_BT601_B	0.114f

#define kHT_Grayscale_BT709_R	0.2126f
#define kHT_Grayscale_BT709_G	0.7152f
#define kHT_Grayscale_BT709_B	0.0722f

#define kHT_Grayscale_Avg_R		0.3333f
#define kHT_Grayscale_Avg_G		0.3334f
#define kHT_Grayscale_Avg_B		0.3333f

/* === Enums === */

typedef unsigned char eHT_GrayMethod;
enum {
	kHT_GrayMethod_BT601 = 0,
	kHT_GrayMethod_BT709,
	kHT_GrayMethod_Average,
	kHT_GrayMethod_COUNT,
};

typedef unsigned char eHT_EdgeMethod;
enum {
	kHT_EdgeMethod_Sobel = 0,
	kHT_EdgeMethod_Scharr,
	kHT_EdgeMethod_Laplacian,
	kHT_EdgeMethod_COUNT,
};

typedef unsigned char eHT_Method;
enum {
	kHT_Method_None = 0,
	kHT_Method_Simple,
	kHT_Method_Box,
	kHT_Method_Atkinson,
	kHT_Method_Burkes,
	kHT_Method_FloydSteinberg,
	kHT_Method_JarvisJudiceNinke,
	kHT_Method_Pigeon,
	kHT_Method_SierraLite,
	kHT_Method_Sierra2,
	kHT_Method_Stucki,
	kHT_Method_COUNT,
};

/* === Structs === */

typedef struct HT_Dither_Biased_Params HT_Dither_Biased_Params;
struct HT_Dither_Biased_Params {
	/* Ordered dither bias */
	unsigned char*		OrderedMatrix;
	unsigned short*		OrderedMatrixU16;
	int					OrderedN;
	float				OrderedMax;
	float				OrderedScale;

	/* Threshold and scanning */
	float				Threshold;
	int					Serpentine;

	/* Error diffusion strength (0.0-1.0). Scales how much quantization
	   error is distributed to neighbors. Values < 1.0 reduce "worm"
	   artifacts. */
	float				DiffusionStrength;
};

/* === Functions === */

HT_DEF int				HT_BilevelSize(int w, int h);

/* Grayscale conversion */
HT_DEF void				HT_GrayscaleFromRGBAWeightedF32(float* out, unsigned char* rgba, int w, int h, float r, float g, float b);
HT_DEF void				HT_GrayscaleFromRGBAF32(float* out, unsigned char* rgba, int w, int h, eHT_GrayMethod method);

/* Tonal adjustment */
HT_DEF void				HT_AdjustF32(float* buf, int w, int h, float gamma, float gain, float contrast, float lift);

/* Sharpening */
HT_DEF void				HT_SharpenF32(float* buf, int w, int h, float* scratch, float amount, int radius);

/* Edge detection */
HT_DEF void				HT_EdgeSobelF32(float* edge_out, float* grayscale, int w, int h);
HT_DEF void				HT_EdgeScharrF32(float* edge_out, float* grayscale, int w, int h);
HT_DEF void				HT_EdgeLaplacianF32(float* edge_out, float* grayscale, int w, int h);
HT_DEF void				HT_EdgeCompositeF32(float* buf, float* edge, int w, int h, float strength);
HT_DEF void				HT_EdgeDetectF32(float* edge_out, float* grayscale, int w, int h, eHT_EdgeMethod method);

/* Ordered dither matrices */
HT_DEF unsigned char*	HT_BayerDefault2(void);
HT_DEF unsigned char*	HT_BayerDefault4(void);
HT_DEF unsigned char*	HT_BayerDefault8(void);
HT_DEF unsigned char*	HT_BayerDefault16(void);
HT_DEF unsigned short*	HT_BayerDefault32(void);
HT_DEF void				HT_WhiteNoiseGenerate64(unsigned char out[4096], int (*rand_fn)(void));
HT_DEF void				HT_IGNGenerate64(unsigned char out[4096]);
HT_DEF void				HT_BlueNoiseGenerate64(unsigned char out[4096], float scratch[12288], int (*rand_fn)(void));
HT_DEF unsigned char*	HT_HalftoneDefault8(void);
HT_DEF unsigned char*	HT_ClusteredDotDiagonal8(void);
HT_DEF unsigned char*	HT_HorizontalLine6(void);
HT_DEF unsigned char*	HT_VerticalLine6(void);

/* Dithering */
HT_DEF void				HT_DitherBiased(unsigned char* out, unsigned char* mask,
							float* work, unsigned char* src_rgba,
							int w, int h,
							eHT_Method diffusion_method,
							HT_Dither_Biased_Params* params);

#endif /* OH4_HALFTONE_H */

#ifdef OH4_HALFTONE_IMPLEMENTATION

#if !defined(HT_Pow) || !defined(HT_Exp)
	#include <math.h>
	#ifndef HT_Pow
		#define HT_Pow(x, e) powf(x, e)
	#endif
	#ifndef HT_Exp
		#define HT_Exp(x) expf(x)
	#endif
#endif

static float ht__clamp(float v, float lo, float hi) {
	float result = v;
	if (result < lo) {
		result = lo;
	} else if (result > hi) {
		result = hi;
	}
	return( result );
}

HT_DEF int HT_BilevelSize(int w, int h) {
	return( ((w * h) + 7) / 8 );
}

/* ==========================================================================
   Grayscale Conversion
   ========================================================================== */

HT_DEF void HT_GrayscaleFromRGBAWeightedF32(float* out, unsigned char* rgba, int w, int h, float r, float g, float b) {
	int count = w * h;
	int i;
	for (i = 0; i < count; i++) {
		out[i] = (float)rgba[i * 4 + 0] * r + (float)rgba[i * 4 + 1] * g + (float)rgba[i * 4 + 2] * b;
	}
}

HT_DEF void HT_GrayscaleFromRGBAF32(float* out, unsigned char* rgba, int w, int h, eHT_GrayMethod method) {
	switch (method) {
		case kHT_GrayMethod_BT601:   { HT_GrayscaleFromRGBAWeightedF32(out, rgba, w, h, kHT_Grayscale_BT601_R, kHT_Grayscale_BT601_G, kHT_Grayscale_BT601_B); } break;
		case kHT_GrayMethod_BT709:   { HT_GrayscaleFromRGBAWeightedF32(out, rgba, w, h, kHT_Grayscale_BT709_R, kHT_Grayscale_BT709_G, kHT_Grayscale_BT709_B); } break;
		case kHT_GrayMethod_Average: { HT_GrayscaleFromRGBAWeightedF32(out, rgba, w, h, kHT_Grayscale_Avg_R,   kHT_Grayscale_Avg_G,   kHT_Grayscale_Avg_B); } break;
		default:                     { HT_GrayscaleFromRGBAWeightedF32(out, rgba, w, h, kHT_Grayscale_BT601_R, kHT_Grayscale_BT601_G, kHT_Grayscale_BT601_B); } break;
	}
}

/* ==========================================================================
   HT_Adjust
   ========================================================================== */

HT_DEF void HT_AdjustF32(float* buf, int w, int h, float gamma, float gain, float contrast, float lift) {
	int count = w * h;
	int i;
	for (i = 0; i < count; i++) {
		float v = buf[i];
		v = HT_Pow(v / 255.0f, gamma) * 255.0f;
		v = v * gain;
		v = (v - 128.0f) * contrast + 128.0f + lift * 255.0f;
		buf[i] = v;
	}
}

/* ==========================================================================
   Edge Detection (F32)
   ========================================================================== */

static void ht__edge_gradient_f32(float* edge_out, float* grayscale, int w, int h, int w0, int w1, int w2, float divisor) {
	int x, y;

	for (x = 0; x < w; x++) {
		edge_out[x] = 0.0f;
		edge_out[(h - 1) * w + x] = 0.0f;
	}
	for (y = 0; y < h; y++) {
		edge_out[y * w] = 0.0f;
		edge_out[y * w + (w - 1)] = 0.0f;
	}

	for (y = 1; y < h - 1; y++) {
		for (x = 1; x < w - 1; x++) {
			float tl = grayscale[(y - 1) * w + (x - 1)];
			float tc = grayscale[(y - 1) * w + x];
			float tr = grayscale[(y - 1) * w + (x + 1)];
			float ml = grayscale[y * w + (x - 1)];
			float mr = grayscale[y * w + (x + 1)];
			float bl = grayscale[(y + 1) * w + (x - 1)];
			float bc = grayscale[(y + 1) * w + x];
			float br = grayscale[(y + 1) * w + (x + 1)];

			float gx = (float)(-w0) * tl + (float)w0 * tr + (float)(-w1) * ml + (float)w1 * mr + (float)(-w2) * bl + (float)w2 * br;
			float gy = (float)(-w0) * tl + (float)(-w1) * tc + (float)(-w2) * tr + (float)w0 * bl + (float)w1 * bc + (float)w2 * br;

			float mag = (gx < 0.0f ? -gx : gx) + (gy < 0.0f ? -gy : gy);
			mag = mag / divisor;
			if (mag > 255.0f) { mag = 255.0f; }
			edge_out[y * w + x] = mag;
		}
	}
}

HT_DEF void HT_EdgeSobelF32(float* edge_out, float* grayscale, int w, int h) {
	ht__edge_gradient_f32(edge_out, grayscale, w, h, 1, 2, 1, 2.0f);
}

HT_DEF void HT_EdgeScharrF32(float* edge_out, float* grayscale, int w, int h) {
	ht__edge_gradient_f32(edge_out, grayscale, w, h, 3, 10, 3, 16.0f);
}

HT_DEF void HT_EdgeLaplacianF32(float* edge_out, float* grayscale, int w, int h) {
	int x, y;

	for (x = 0; x < w; x++) {
		edge_out[x] = 0.0f;
		edge_out[(h - 1) * w + x] = 0.0f;
	}
	for (y = 0; y < h; y++) {
		edge_out[y * w] = 0.0f;
		edge_out[y * w + (w - 1)] = 0.0f;
	}

	for (y = 1; y < h - 1; y++) {
		for (x = 1; x < w - 1; x++) {
			float sum = grayscale[(y - 1) * w + (x - 1)]
					  + grayscale[(y - 1) * w + x]
					  + grayscale[(y - 1) * w + (x + 1)]
					  + grayscale[y * w + (x - 1)]
					  - 8.0f * grayscale[y * w + x]
					  + grayscale[y * w + (x + 1)]
					  + grayscale[(y + 1) * w + (x - 1)]
					  + grayscale[(y + 1) * w + x]
					  + grayscale[(y + 1) * w + (x + 1)];
			if (sum < 0.0f) { sum = -sum; }
			if (sum > 255.0f) { sum = 255.0f; }
			edge_out[y * w + x] = sum;
		}
	}
}

HT_DEF void HT_EdgeCompositeF32(float* buf, float* edge, int w, int h, float strength) {
	int count = w * h;
	int i;
	for (i = 0; i < count; i++) {
		float v = buf[i] - edge[i] * strength;
		buf[i] = ht__clamp(v, 0.0f, 255.0f);
	}
}

HT_DEF void HT_EdgeDetectF32(float* edge_out, float* grayscale, int w, int h, eHT_EdgeMethod method) {
	switch (method) {
		case kHT_EdgeMethod_Sobel:     { HT_EdgeSobelF32(edge_out, grayscale, w, h); } break;
		case kHT_EdgeMethod_Scharr:    { HT_EdgeScharrF32(edge_out, grayscale, w, h); } break;
		case kHT_EdgeMethod_Laplacian: { HT_EdgeLaplacianF32(edge_out, grayscale, w, h); } break;
		default: break;
	}
}

/* ==========================================================================
   Bayer Matrices
   ========================================================================== */

static unsigned char ht__bayer2[4] = {
	0, 2,
	3, 1,
};

static unsigned char ht__bayer4[16] = {
	 0,  8,  2, 10,
	12,  4, 14,  6,
	 3, 11,  1,  9,
	15,  7, 13,  5,
};

static unsigned char ht__bayer8[64] = {
	 0, 32,  8, 40,  2, 34, 10, 42,
	48, 16, 56, 24, 50, 18, 58, 26,
	12, 44,  4, 36, 14, 46,  6, 38,
	60, 28, 52, 20, 62, 30, 54, 22,
	 3, 35, 11, 43,  1, 33,  9, 41,
	51, 19, 59, 27, 49, 17, 57, 25,
	15, 47,  7, 39, 13, 45,  5, 37,
	63, 31, 55, 23, 61, 29, 53, 21,
};

static unsigned char ht__bayer16[256] = {
	   0,  128,   32,  160,    8,  136,   40,  168,    2,  130,   34,  162,   10,  138,   42,  170,
	 192,   64,  224,   96,  200,   72,  232,  104,  194,   66,  226,   98,  202,   74,  234,  106,
	  48,  176,   16,  144,   56,  184,   24,  152,   50,  178,   18,  146,   58,  186,   26,  154,
	 240,  112,  208,   80,  248,  120,  216,   88,  242,  114,  210,   82,  250,  122,  218,   90,
	  12,  140,   44,  172,    4,  132,   36,  164,   14,  142,   46,  174,    6,  134,   38,  166,
	 204,   76,  236,  108,  196,   68,  228,  100,  206,   78,  238,  110,  198,   70,  230,  102,
	  60,  188,   28,  156,   52,  180,   20,  148,   62,  190,   30,  158,   54,  182,   22,  150,
	 252,  124,  220,   92,  244,  116,  212,   84,  254,  126,  222,   94,  246,  118,  214,   86,
	   3,  131,   35,  163,   11,  139,   43,  171,    1,  129,   33,  161,    9,  137,   41,  169,
	 195,   67,  227,   99,  203,   75,  235,  107,  193,   65,  225,   97,  201,   73,  233,  105,
	  51,  179,   19,  147,   59,  187,   27,  155,   49,  177,   17,  145,   57,  185,   25,  153,
	 243,  115,  211,   83,  251,  123,  219,   91,  241,  113,  209,   81,  249,  121,  217,   89,
	  15,  143,   47,  175,    7,  135,   39,  167,   13,  141,   45,  173,    5,  133,   37,  165,
	 207,   79,  239,  111,  199,   71,  231,  103,  205,   77,  237,  109,  197,   69,  229,  101,
	  63,  191,   31,  159,   55,  183,   23,  151,   61,  189,   29,  157,   53,  181,   21,  149,
	 255,  127,  223,   95,  247,  119,  215,   87,  253,  125,  221,   93,  245,  117,  213,   85,
};

static unsigned short ht__bayer32[1024] = {
	   0,  512,  128,  640,   32,  544,  160,  672,    8,  520,  136,  648,   40,  552,  168,  680,
	   2,  514,  130,  642,   34,  546,  162,  674,   10,  522,  138,  650,   42,  554,  170,  682,
	 768,  256,  896,  384,  800,  288,  928,  416,  776,  264,  904,  392,  808,  296,  936,  424,
	 770,  258,  898,  386,  802,  290,  930,  418,  778,  266,  906,  394,  810,  298,  938,  426,
	 192,  704,   64,  576,  224,  736,   96,  608,  200,  712,   72,  584,  232,  744,  104,  616,
	 194,  706,   66,  578,  226,  738,   98,  610,  202,  714,   74,  586,  234,  746,  106,  618,
	 960,  448,  832,  320,  992,  480,  864,  352,  968,  456,  840,  328, 1000,  488,  872,  360,
	 962,  450,  834,  322,  994,  482,  866,  354,  970,  458,  842,  330, 1002,  490,  874,  362,
	  48,  560,  176,  688,   16,  528,  144,  656,   56,  568,  184,  696,   24,  536,  152,  664,
	  50,  562,  178,  690,   18,  530,  146,  658,   58,  570,  186,  698,   26,  538,  154,  666,
	 816,  304,  944,  432,  784,  272,  912,  400,  824,  312,  952,  440,  792,  280,  920,  408,
	 818,  306,  946,  434,  786,  274,  914,  402,  826,  314,  954,  442,  794,  282,  922,  410,
	 240,  752,  112,  624,  208,  720,   80,  592,  248,  760,  120,  632,  216,  728,   88,  600,
	 242,  754,  114,  626,  210,  722,   82,  594,  250,  762,  122,  634,  218,  730,   90,  602,
	1008,  496,  880,  368,  976,  464,  848,  336, 1016,  504,  888,  376,  984,  472,  856,  344,
	1010,  498,  882,  370,  978,  466,  850,  338, 1018,  506,  890,  378,  986,  474,  858,  346,
	  12,  524,  140,  652,   44,  556,  172,  684,    4,  516,  132,  644,   36,  548,  164,  676,
	  14,  526,  142,  654,   46,  558,  174,  686,    6,  518,  134,  646,   38,  550,  166,  678,
	 780,  268,  908,  396,  812,  300,  940,  428,  772,  260,  900,  388,  804,  292,  932,  420,
	 782,  270,  910,  398,  814,  302,  942,  430,  774,  262,  902,  390,  806,  294,  934,  422,
	 204,  716,   76,  588,  236,  748,  108,  620,  196,  708,   68,  580,  228,  740,  100,  612,
	 206,  718,   78,  590,  238,  750,  110,  622,  198,  710,   70,  582,  230,  742,  102,  614,
	 972,  460,  844,  332, 1004,  492,  876,  364,  964,  452,  836,  324,  996,  484,  868,  356,
	 974,  462,  846,  334, 1006,  494,  878,  366,  966,  454,  838,  326,  998,  486,  870,  358,
	  60,  572,  188,  700,   28,  540,  156,  668,   52,  564,  180,  692,   20,  532,  148,  660,
	  62,  574,  190,  702,   30,  542,  158,  670,   54,  566,  182,  694,   22,  534,  150,  662,
	 828,  316,  956,  444,  796,  284,  924,  412,  820,  308,  948,  436,  788,  276,  916,  404,
	 830,  318,  958,  446,  798,  286,  926,  414,  822,  310,  950,  438,  790,  278,  918,  406,
	 252,  764,  124,  636,  220,  732,   92,  604,  244,  756,  116,  628,  212,  724,   84,  596,
	 254,  766,  126,  638,  222,  734,   94,  606,  246,  758,  118,  630,  214,  726,   86,  598,
	1020,  508,  892,  380,  988,  476,  860,  348, 1012,  500,  884,  372,  980,  468,  852,  340,
	1022,  510,  894,  382,  990,  478,  862,  350, 1014,  502,  886,  374,  982,  470,  854,  342,
	   3,  515,  131,  643,   35,  547,  163,  675,   11,  523,  139,  651,   43,  555,  171,  683,
	   1,  513,  129,  641,   33,  545,  161,  673,    9,  521,  137,  649,   41,  553,  169,  681,
	 771,  259,  899,  387,  803,  291,  931,  419,  779,  267,  907,  395,  811,  299,  939,  427,
	 769,  257,  897,  385,  801,  289,  929,  417,  777,  265,  905,  393,  809,  297,  937,  425,
	 195,  707,   67,  579,  227,  739,   99,  611,  203,  715,   75,  587,  235,  747,  107,  619,
	 193,  705,   65,  577,  225,  737,   97,  609,  201,  713,   73,  585,  233,  745,  105,  617,
	 963,  451,  835,  323,  995,  483,  867,  355,  971,  459,  843,  331, 1003,  491,  875,  363,
	 961,  449,  833,  321,  993,  481,  865,  353,  969,  457,  841,  329, 1001,  489,  873,  361,
	  51,  563,  179,  691,   19,  531,  147,  659,   59,  571,  187,  699,   27,  539,  155,  667,
	  49,  561,  177,  689,   17,  529,  145,  657,   57,  569,  185,  697,   25,  537,  153,  665,
	 819,  307,  947,  435,  787,  275,  915,  403,  827,  315,  955,  443,  795,  283,  923,  411,
	 817,  305,  945,  433,  785,  273,  913,  401,  825,  313,  953,  441,  793,  281,  921,  409,
	 243,  755,  115,  627,  211,  723,   83,  595,  251,  763,  123,  635,  219,  731,   91,  603,
	 241,  753,  113,  625,  209,  721,   81,  593,  249,  761,  121,  633,  217,  729,   89,  601,
	1011,  499,  883,  371,  979,  467,  851,  339, 1019,  507,  891,  379,  987,  475,  859,  347,
	1009,  497,  881,  369,  977,  465,  849,  337, 1017,  505,  889,  377,  985,  473,  857,  345,
	  15,  527,  143,  655,   47,  559,  175,  687,    7,  519,  135,  647,   39,  551,  167,  679,
	  13,  525,  141,  653,   45,  557,  173,  685,    5,  517,  133,  645,   37,  549,  165,  677,
	 783,  271,  911,  399,  815,  303,  943,  431,  775,  263,  903,  391,  807,  295,  935,  423,
	 781,  269,  909,  397,  813,  301,  941,  429,  773,  261,  901,  389,  805,  293,  933,  421,
	 207,  719,   79,  591,  239,  751,  111,  623,  199,  711,   71,  583,  231,  743,  103,  615,
	 205,  717,   77,  589,  237,  749,  109,  621,  197,  709,   69,  581,  229,  741,  101,  613,
	 975,  463,  847,  335, 1007,  495,  879,  367,  967,  455,  839,  327,  999,  487,  871,  359,
	 973,  461,  845,  333, 1005,  493,  877,  365,  965,  453,  837,  325,  997,  485,  869,  357,
	  63,  575,  191,  703,   31,  543,  159,  671,   55,  567,  183,  695,   23,  535,  151,  663,
	  61,  573,  189,  701,   29,  541,  157,  669,   53,  565,  181,  693,   21,  533,  149,  661,
	 831,  319,  959,  447,  799,  287,  927,  415,  823,  311,  951,  439,  791,  279,  919,  407,
	 829,  317,  957,  445,  797,  285,  925,  413,  821,  309,  949,  437,  789,  277,  917,  405,
	 255,  767,  127,  639,  223,  735,   95,  607,  247,  759,  119,  631,  215,  727,   87,  599,
	 253,  765,  125,  637,  221,  733,   93,  605,  245,  757,  117,  629,  213,  725,   85,  597,
	1023,  511,  895,  383,  991,  479,  863,  351, 1015,  503,  887,  375,  983,  471,  855,  343,
	1021,  509,  893,  381,  989,  477,  861,  349, 1013,  501,  885,  373,  981,  469,  853,  341,
};

HT_DEF unsigned char* HT_BayerDefault2(void)   { return( ht__bayer2 ); }
HT_DEF unsigned char* HT_BayerDefault4(void)   { return( ht__bayer4 ); }
HT_DEF unsigned char* HT_BayerDefault8(void)   { return( ht__bayer8 ); }
HT_DEF unsigned char* HT_BayerDefault16(void)  { return( ht__bayer16 ); }
HT_DEF unsigned short* HT_BayerDefault32(void) { return( ht__bayer32 ); }

HT_DEF void HT_WhiteNoiseGenerate64(unsigned char out[4096], int (*rand_fn)(void)) {
	int i;
	for (i = 0; i < 4096; i++) {
		out[i] = (unsigned char)(rand_fn() % 256);
	}
}

HT_DEF void HT_IGNGenerate64(unsigned char out[4096]) {
	int x, y;
	for (y = 0; y < 64; y++) {
		for (x = 0; x < 64; x++) {
			double dot = 0.06711056 * (double)x + 0.00583715 * (double)y;
			double inner = dot - (int)dot; /* fract */
			double outer = 52.9829189 * inner;
			double frac = outer - (int)outer; /* fract */
			int val;
			if (frac < 0.0) { frac += 1.0; }
			val = (int)(frac * 255.0 + 0.5);
			if (val > 255) { val = 255; }
			out[y * 64 + x] = (unsigned char)val;
		}
	}
}

/* ==========================================================================
   Blue Noise Generation (void-and-cluster algorithm)
   Incremental energy updates based on approach by Martin Fiedler (kajott).
   ========================================================================== */

#define HT__BN_GET(bmp, i)  (((bmp)[(i) >> 5] >> ((i) & 31)) & 1u)
#define HT__BN_SET(bmp, i)  do { (bmp)[(i) >> 5] |=  (1u << ((i) & 31)); } while (0)
#define HT__BN_CLR(bmp, i)  do { (bmp)[(i) >> 5] &= ~(1u << ((i) & 31)); } while (0)

static void ht__bn_update(float* energy, unsigned int* bitmap, int index, float sign,
                           float lut[17][17], int* out_imin, int* out_imax) {
	int px = index & 63, py = index >> 6;
	float emin = 1e30f, emax = -1e30f;
	int imin = 0, imax = 0;
	int i;
	for (i = 0; i < 4096; i++) {
		int x = i & 63, y = i >> 6;
		int dx = x - px, dy = y - py;
		if (dx >  31) { dx -= 64; } else if (dx < -32) { dx += 64; }
		if (dy >  31) { dy -= 64; } else if (dy < -32) { dy += 64; }
		if (dx >= -8 && dx <= 8 && dy >= -8 && dy <= 8) {
			energy[i] += lut[dy + 8][dx + 8] * sign;
		}
		if (HT__BN_GET(bitmap, i)) {
			if (energy[i] > emax) { emax = energy[i]; imax = i; }
		} else {
			if (energy[i] < emin) { emin = energy[i]; imin = i; }
		}
	}
	*out_imin = imin;
	*out_imax = imax;
}

HT_DEF void HT_BlueNoiseGenerate64(unsigned char out[4096], float scratch[12288], int (*rand_fn)(void)) {
	float*        energy       = scratch;
	float*        saved_energy = scratch + 4096;
	unsigned int  bitmap[128];
	unsigned int  saved_bitmap[128];
	float         lut[17][17];
	int           imin = 0, imax = 0, points = 0, i;
	float         sigma = 1.5f;
	float         inv_2sigma2 = 1.0f / (2.0f * sigma * sigma);

	/* Build Gaussian LUT */
	{
		int dx, dy;
		for (dy = -8; dy <= 8; dy++) {
			for (dx = -8; dx <= 8; dx++) {
				lut[dy + 8][dx + 8] = HT_Exp(-(float)(dx * dx + dy * dy) * inv_2sigma2);
			}
		}
	}

	/* Zero state */
	for (i = 0; i < 4096; i++) { energy[i] = 0.0f; out[i] = 0; }
	for (i = 0; i < 128; i++) { bitmap[i] = 0; }

	/* Seed ~10% random points */
	{
		int initial_count = 4096 / 10;
		while (points < initial_count) {
			int idx = rand_fn() & 4095;
			if (!HT__BN_GET(bitmap, idx)) {
				HT__BN_SET(bitmap, idx);
				ht__bn_update(energy, bitmap, idx, +1.0f, lut, &imin, &imax);
				points++;
			}
		}
	}

	/* Tighten: redistribute until convergence */
	{
		int last = -1;
		while (imax != last) {
			HT__BN_CLR(bitmap, imax);
			ht__bn_update(energy, bitmap, imax, -1.0f, lut, &imin, &imax);
			last = imin;
			HT__BN_SET(bitmap, imin);
			ht__bn_update(energy, bitmap, imin, +1.0f, lut, &imin, &imax);
		}
	}

	/* Save balanced state */
	for (i = 0; i < 4096; i++) { saved_energy[i] = energy[i]; }
	for (i = 0; i < 128; i++) { saved_bitmap[i] = bitmap[i]; }

	/* Phase 1: remove tightest clusters, assign decreasing ranks */
	{
		int rank = points - 1;
		while (rank >= 0) {
			out[imax] = (unsigned char)((rank * 255) / 4095);
			HT__BN_CLR(bitmap, imax);
			ht__bn_update(energy, bitmap, imax, -1.0f, lut, &imin, &imax);
			rank--;
		}
	}

	/* Restore balanced state */
	for (i = 0; i < 4096; i++) { energy[i] = saved_energy[i]; }
	for (i = 0; i < 128; i++) { bitmap[i] = saved_bitmap[i]; }

	/* Phase 2: fill voids, assign increasing ranks up to half */
	{
		int rank = points;
		while (rank < 2048) {
			out[imin] = (unsigned char)((rank * 255) / 4095);
			HT__BN_SET(bitmap, imin);
			ht__bn_update(energy, bitmap, imin, +1.0f, lut, &imin, &imax);
			rank++;
		}
		points = rank;
	}

	/* Invert bitmap and rebuild energy for the empty side */
	for (i = 0; i < 128; i++) { bitmap[i] ^= ~0u; }
	for (i = 0; i < 4096; i++) { energy[i] = 0.0f; }
	for (i = 0; i < 4096; i++) {
		if (HT__BN_GET(bitmap, i)) {
			ht__bn_update(energy, bitmap, i, +1.0f, lut, &imin, &imax);
		}
	}

	/* Phase 3: remove tightest from inverted side, assign remaining ranks */
	while (points < 4096) {
		out[imax] = (unsigned char)((points * 255) / 4095);
		HT__BN_CLR(bitmap, imax);
		ht__bn_update(energy, bitmap, imax, -1.0f, lut, &imin, &imax);
		points++;
	}
}

#undef HT__BN_GET
#undef HT__BN_SET
#undef HT__BN_CLR

HT_DEF unsigned char* HT_HalftoneDefault8(void) {
	/* 8x8 clustered-dot: values 0-63, closest to center activate first */
	static unsigned char ht__halftone8[64] = {
		63, 58, 50, 40, 41, 51, 59, 60,
		57, 33, 27, 18, 19, 28, 34, 52,
		49, 26, 13,  7,  8, 14, 29, 43,
		39, 17,  6,  1,  2,  9, 20, 35,
		38, 16,  5,  0,  3, 10, 21, 36,
		48, 25, 12,  4, 11, 15, 30, 44,
		56, 32, 24, 23, 22, 31, 37, 53,
		62, 55, 47, 46, 45, 42, 54, 61,
	};
	return ht__halftone8;
}

HT_DEF unsigned char* HT_ClusteredDotDiagonal8(void) {
	/* 8x8 diagonal clustered-dot: 45-degree rotated halftone screen (comic book / newspaper look) */
	static unsigned char ht__clustered_dot_diagonal_8x8[64] = {
		24, 10, 12, 26, 35, 47, 49, 37,
		 8,  0,  2, 14, 45, 59, 61, 51,
		22,  6,  4, 16, 43, 57, 63, 53,
		30, 20, 18, 28, 33, 41, 55, 39,
		34, 46, 48, 36, 25, 11, 13, 27,
		44, 58, 60, 50,  9,  1,  3, 15,
		42, 56, 62, 52, 23,  7,  5, 17,
		32, 40, 54, 38, 31, 21, 19, 29,
	};
	return ht__clustered_dot_diagonal_8x8;
}

HT_DEF unsigned char* HT_HorizontalLine6(void) {
	/* 6x6 horizontal line screen: produces scanline / engraving look */
	static unsigned char ht__horizontal_line_6x6[36] = {
		35, 33, 31, 30, 32, 34,
		23, 21, 19, 18, 20, 22,
		11,  9,  7,  6,  8, 10,
		 5,  3,  1,  0,  2,  4,
		17, 15, 13, 12, 14, 16,
		29, 27, 25, 24, 26, 28,
	};
	return ht__horizontal_line_6x6;
}

HT_DEF unsigned char* HT_VerticalLine6(void) {
	/* 6x6 vertical line screen: produces vertical stripe pattern */
	static unsigned char ht__vertical_line_6x6[36] = {
		35, 23, 11,  5, 17, 29,
		33, 21,  9,  3, 15, 27,
		31, 19,  7,  1, 13, 25,
		30, 18,  6,  0, 12, 24,
		32, 20,  8,  2, 14, 26,
		34, 22, 10,  4, 16, 28,
	};
	return ht__vertical_line_6x6;
}

typedef struct {
	signed char dx;
	signed char dy;
	unsigned char weight;
} ht__kernel_entry;

typedef struct {
	ht__kernel_entry* entries;
	int count;
	int scale;
} ht__kernel;

static ht__kernel_entry ht__simple_entries[] = {
	{ 1, 0, 1 },
	{ 0, 1, 1 },
};

static ht__kernel_entry ht__box_entries[] = {
	{  1, 0, 1 },
	{ -1, 1, 1 },
	{  0, 1, 1 },
	{  1, 1, 1 },
};

static ht__kernel_entry ht__atkinson_entries[] = {
	{  1, 0, 1 },
	{  2, 0, 1 },
	{ -1, 1, 1 },
	{  0, 1, 1 },
	{  1, 1, 1 },
	{  0, 2, 1 },
};

static ht__kernel_entry ht__burkes_entries[] = {
	{  1, 0, 8 },
	{  2, 0, 4 },
	{ -2, 1, 2 },
	{ -1, 1, 4 },
	{  0, 1, 8 },
	{  1, 1, 4 },
	{  2, 1, 2 },
};

static ht__kernel_entry ht__floyd_steinberg_entries[] = {
	{  1, 0, 7 },
	{ -1, 1, 3 },
	{  0, 1, 5 },
	{  1, 1, 1 },
};

static ht__kernel_entry ht__jarvis_judice_ninke_entries[] = {
	{  1, 0, 7 },
	{  2, 0, 5 },
	{ -2, 1, 3 },
	{ -1, 1, 5 },
	{  0, 1, 7 },
	{  1, 1, 5 },
	{  2, 1, 3 },
	{ -1, 2, 3 },
	{  0, 2, 5 },
	{  1, 2, 3 },
};

static ht__kernel_entry ht__pigeon_entries[] = {
	{  1, 0, 2 },
	{  2, 0, 1 },
	{ -1, 1, 2 },
	{  0, 1, 2 },
	{  1, 1, 2 },
	{ -2, 2, 1 },
	{  0, 2, 1 },
	{  2, 2, 1 },
};

static ht__kernel_entry ht__sierra_lite_entries[] = {
	{  1, 0, 2 },
	{ -1, 1, 1 },
	{  0, 1, 1 },
};

static ht__kernel_entry ht__sierra2_entries[] = {
	{  1, 0, 4 },
	{  2, 0, 3 },
	{ -2, 1, 1 },
	{ -1, 1, 2 },
	{  0, 1, 3 },
	{  1, 1, 2 },
	{  2, 1, 1 },
};

static ht__kernel_entry ht__stucki_entries[] = {
	{  1, 0, 8 },
	{  2, 0, 4 },
	{ -2, 1, 2 },
	{ -1, 1, 4 },
	{  0, 1, 8 },
	{  1, 1, 4 },
	{  2, 1, 2 },
	{ -2, 2, 1 },
	{ -1, 2, 2 },
	{  0, 2, 4 },
	{  1, 2, 2 },
	{  2, 2, 1 },
};

static ht__kernel ht__kernel_simple					= { ht__simple_entries,               2,  2 };
static ht__kernel ht__kernel_box               		= { ht__box_entries,                  4,  4 };
static ht__kernel ht__kernel_atkinson          		= { ht__atkinson_entries,             6,  8 };
static ht__kernel ht__kernel_burkes            		= { ht__burkes_entries,               7, 32 };
static ht__kernel ht__kernel_floyd_steinberg   		= { ht__floyd_steinberg_entries,      4, 16 };
static ht__kernel ht__kernel_jarvis_judice_ninke	= { ht__jarvis_judice_ninke_entries, 10, 46 };
static ht__kernel ht__kernel_pigeon            		= { ht__pigeon_entries,               8, 14 };
static ht__kernel ht__kernel_sierra_lite       		= { ht__sierra_lite_entries,          3,  4 };
static ht__kernel ht__kernel_sierra2           		= { ht__sierra2_entries,              7, 16 };
static ht__kernel ht__kernel_stucki            		= { ht__stucki_entries,              12, 42 };

/* ==========================================================================
   Sharpening (unsharp mask)
   ========================================================================== */

HT_DEF void HT_SharpenF32(float* buf, int w, int h, float* scratch, float amount, int radius) {
	if (radius > 0 && amount != 0.0f) {
		int count = w * h;
		int x, y, dx, dy;
		int diam = 2 * radius + 1;
		float inv_area = 1.0f / (float)(diam * diam);
		for (y = 0; y < h; y++) {
			for (x = 0; x < w; x++) {
				float sum = 0.0f;
				for (dy = -radius; dy <= radius; dy++) {
					int sy = y + dy;
					if (sy < 0) { sy = 0; }
					if (sy >= h) { sy = h - 1; }
					for (dx = -radius; dx <= radius; dx++) {
						int sx = x + dx;
						if (sx < 0) { sx = 0; }
						if (sx >= w) { sx = w - 1; }
						sum += buf[sy * w + sx];
					}
				}
				scratch[y * w + x] = sum * inv_area;
			}
		}
		for (y = 0; y < count; y++) {
			buf[y] = buf[y] + amount * (buf[y] - scratch[y]);
		}
	}
}

/* ==========================================================================
   HT_DitherBiased
   ========================================================================== */

static ht__kernel* ht__kernel_from_method(eHT_Method method) {
	switch (method) {
		case kHT_Method_None:              { return( 0 ); }
		case kHT_Method_Simple:            { return( &ht__kernel_simple ); }
		case kHT_Method_Box:               { return( &ht__kernel_box ); }
		case kHT_Method_Atkinson:          { return( &ht__kernel_atkinson ); }
		case kHT_Method_Burkes:            { return( &ht__kernel_burkes ); }
		case kHT_Method_FloydSteinberg:    { return( &ht__kernel_floyd_steinberg ); }
		case kHT_Method_JarvisJudiceNinke: { return( &ht__kernel_jarvis_judice_ninke ); }
		case kHT_Method_Pigeon:            { return( &ht__kernel_pigeon ); }
		case kHT_Method_SierraLite:        { return( &ht__kernel_sierra_lite ); }
		case kHT_Method_Sierra2:           { return( &ht__kernel_sierra2 ); }
		case kHT_Method_Stucki:            { return( &ht__kernel_stucki ); }
		default:                           { return( 0 ); }
	}
}

HT_DEF void HT_DitherBiased(unsigned char* out, unsigned char* mask,
                             float* work, unsigned char* src_rgba,
                             int w, int h,
                             eHT_Method diffusion_method,
                             HT_Dither_Biased_Params* params) {
	ht__kernel* kernel = ht__kernel_from_method(diffusion_method);
	int has_ordered = (params->OrderedMatrix || params->OrderedMatrixU16) && params->OrderedMax > 0.0f;
	float bayer_scale = 0.0f;
	float strength = params->DiffusionStrength;
	int x, y, k;
	if (has_ordered) {
		bayer_scale = params->OrderedScale * (255.0f / params->OrderedMax);
	}

	for (y = 0; y < h; y++) {
		int reverse = params->Serpentine && (y & 1);
		int x_start = reverse ? w - 1 : 0;
		int x_end   = reverse ? -1 : w;
		int x_step  = reverse ? -1 : 1;
		for (x = x_start; x != x_end; x += x_step) {
			int i = y * w + x;
			float lum = work[i];
			int out_bit;

			/* Add ordered dither bias */
			if (has_ordered) {
				int mi = (x % params->OrderedN) + (y % params->OrderedN) * params->OrderedN;
				float mv = params->OrderedMatrix
					? (float)params->OrderedMatrix[mi]
					: (float)params->OrderedMatrixU16[mi];
				float bd = (mv - params->OrderedMax * 0.5f) * bayer_scale;
				lum += bd;
			}

			/* Threshold */
			out_bit = lum > params->Threshold ? 1 : 0;
			if (out_bit) {
				out[i / 8] |= (unsigned char)(1 << (7 - (i % 8)));
			}

			/* Alpha mask */
			if (mask && src_rgba) {
				unsigned char alpha = src_rgba[i * 4 + 3];
				if (alpha >= 128) {
					mask[i / 8] |= (unsigned char)(1 << (7 - (i % 8)));
				}
			}

			/* Error diffusion */
			if (kernel) {
				float err = (lum - (out_bit ? 255.0f : 0.0f)) * strength;
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

#endif /* OH4_HALFTONE_IMPLEMENTATION */
