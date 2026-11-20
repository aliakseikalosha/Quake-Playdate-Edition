/*
 * qpeview: the real engine (winquake/ with the Playdate renderer, pdr_*.c) and the real Playdate display
 * code (port/boards/playdate/display.c), run headless on the host and driven over stdin/stdout by
 * tools/qpe/qpe.py serve, the side-by-side comparison tool of the "Quake: Playdate Edition" mod.
 *
 * Two of these run at once: one on the original data (id1) and one with "-game qpe". Every frame is
 * returned twice: the 8-bit picture Quake drew (with its palette, for the full-colour view) and the
 * 1-bit LCD image display.c made from it (exactly what the Playdate shows).
 *
 * Protocol: one command per line on stdin. Every command answers with one line on stdout,
 * "OK", "OK {json}" or "ERR text"; "frame" answers "FRAME <bytes>" followed by that many bytes:
 *     768 bytes palette (RGB) | 400*240 bytes 8-bit picture | 240 rows * 50 bytes LCD (MSB = left, 1 = white)
 * Console output goes to stderr. A Sys_Error prints "FATAL text" and exits (the server restarts us).
 *
 *   c <console text>                 queue console commands (Cbuf_AddText)
 *   run <n>                          run n frames (33 ms each on the fake clock)
 *   load <map>                       start that map and run frames until the client is in; answers
 *                                    {"origin":[..],"angles":[..],"mins":[..],"maxs":[..]}
 *   cam off | cam x y z pitch yaw roll
 *                                    override the view (and move the player there, noclip/god/notarget,
 *                                    so the server sends the entities that are visible from there)
 *   ent off | ent <model> <frame> <skin> x y z pitch yaw roll
 *                                    add one entity (alias model, sprite or brush model) to the view
 *   freeze 0|1                       pause the game (the picture still updates), so both engines show one moment
 *   solo 0|1                         1: draw only that entity (no other entities, particles, dlights)
 *   light off | light <0-255>        fixed light level for that entity (alias models)
 *   vmodel off | vmodel <model> <frame>
 *                                    replace the weapon in hand with that model
 *   ui none|console|scores|menu      what is shown over the view (menu: whatever menu_* opened)
 *   pic off | pic <name> <bg> | chars <bg> | text <bg>
 *                                    draw a picture ("wad:NAME" from gfx.wad, or a .lmp path), the font
 *                                    sheet or a text sample alone on a filled background
 *   center <text> | center off       a centre-printed message (as triggers print them), '|' = new line
 *   frame <n>                        run n frames, then send the picture
 */
#include <stdio.h>
#include "pd_api.h"
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdint.h>
#include <quakedef.h>
#include <quakembd.h>
#include <d_local.h>
#ifdef PD_STACK
#include <pd_stack.h>
#endif

#define W 400
#define H 240
#define FRAME_BYTES (LCD_ROWSIZE * LCD_ROWS)

PlaydateAPI *qembd_pd;
static struct playdate_graphics gfx;
static PlaydateAPI api;
static uint8_t lcd[FRAME_BYTES];
static uint8_t shot[W * H];		/* the 8-bit picture of the last VID_Update */
static uint8_t shot_pal[768];

void R_ClearParticles(void);
static uint8_t *get_frame(void) { return lcd; }
static void mark_rows(int a, int b) { (void)a; (void)b; }

/* ------------------------------------------------------------------ display */
void tree_fillrect(uint8_t *, uint32_t *, uint16_t, uint16_t, uint16_t, uint16_t);
void tree_vidinit(void);
int tree_get_width(void);
int tree_get_height(void);
int qembd_get_width(void) { return tree_get_width(); }
int qembd_get_height(void) { return tree_get_height(); }
void qembd_refresh(void) {}
void qembd_vidinit(void) { tree_vidinit(); }

void qembd_fillrect(uint8_t *src, uint32_t *clut, uint16_t x, uint16_t y, uint16_t xs, uint16_t ys)
{
	extern int qembd_lowres_active;
	int i;

	/* the LCD exactly as the device makes it ... */
	tree_fillrect(src, clut, x, y, xs, ys);
	/* ... then the view rows that are still only in the half-resolution buffer are expanded into the
	 * 8-bit picture (the hostcheck proves dithering them either way gives the same LCD) */
	if (qembd_lowres_active)
		D_LowresTouch(0, H);
	memcpy(shot, src, W * H);
	for (i = 0; i < 256; i++) {
		shot_pal[i * 3] = (clut[i] >> 16) & 0xff;
		shot_pal[i * 3 + 1] = (clut[i] >> 8) & 0xff;
		shot_pal[i * 3 + 2] = clut[i] & 0xff;
	}
}

/* ------------------------------------------------------------------ stubs (as tools/hostcheck) */
static uint64_t fake_us;
uint64_t qembd_get_us_time(void) { return fake_us; }
void qembd_udelay(uint32_t us) { fake_us += us; }
void *qembd_allocmain(size_t size)
{
	static byte pool[32 * 1024 * 1024] __attribute__((aligned(16)));
	return size <= sizeof(pool) ? pool : NULL;
}
void qembd_log(const char *t) { fputs(t, stderr); }
void qembd_fatal(const char *m) { printf("FATAL %s\n", m); fflush(stdout); exit(2); }
void qembd_quit(void) { exit(0); }
int qembd_dequeue_key_event(key_event_t *e) { (void)e; return -1; }
int qembd_get_mouse_movement(mouse_movement_t *m) { (void)m; return -1; }
void qembd_set_relative_mode(bool e) { (void)e; }
void qembd_restart(const char *g) { (void)g; }

cvar_t bgmvolume = {"bgmvolume", "1", true};
cvar_t volume = {"volume", "0.7", true};
vec_t sound_nominal_clip_dist = 1000.0;
void S_Init(void) {}
void S_Startup(void) {}
void S_Shutdown(void) {}
void S_StartSound(int a, int b, sfx_t *s, vec3_t o, float v, float at) {}
void S_StaticSound(sfx_t *s, vec3_t o, float v, float a) {}
void S_StopSound(int a, int b) {}
void S_StopAllSounds(qboolean c) {}
void S_ClearBuffer(void) {}
void S_Update(vec3_t o, vec3_t f, vec3_t r, vec3_t u) {}
void S_ExtraUpdate(void) {}
sfx_t *S_PrecacheSound(char *s) { return NULL; }
void S_TouchSound(char *s) {}
void S_ClearPrecache(void) {}
void S_BeginPrecaching(void) {}
void S_EndPrecaching(void) {}
void S_LocalSound(char *s) {}
void S_AmbientOff(void) {}
void S_AmbientOn(void) {}

/* ------------------------------------------------------------------ viewer state */
static int cam_on;
static vec3_t cam_org, cam_ang;
static entity_t qent;
static int ent_on, solo, light_ovr = -1;
static model_t *vmodel;
static int vmodel_frame;
enum { PIC_OFF, PIC_PIC, PIC_CHARS, PIC_TEXT };
static int pic_mode, pic_bg;
static char pic_name[128];

/* pdr_main.c is compiled with R_RenderView renamed: this runs after V_RenderView set up r_refdef */
void real_R_RenderView(void);
void R_RenderView(void)
{
	if (cam_on) {
		VectorCopy(cam_org, r_refdef.vieworg);
		VectorCopy(cam_ang, r_refdef.viewangles);
	}
	if (solo) {
		cl_numvisedicts = 0;
		R_ClearParticles();
		memset(cl_dlights, 0, sizeof(cl_dlights));
	}
	if (ent_on && qent.model && cl_numvisedicts < MAX_VISEDICTS)
		cl_visedicts[cl_numvisedicts++] = &qent;
	if (vmodel) {
		cl.viewent.model = vmodel;
		cl.viewent.frame = vmodel_frame;
	}
	real_R_RenderView();
}

/* pdr_light.c is compiled with PDR_LightPoint renamed: a fixed light for the viewer's entity */
int real_PDR_LightPoint(const vec3_t p);
int PDR_LightPoint(const vec3_t p)
{
	if (light_ovr >= 0 && ent_on && p == qent.origin)
		return light_ovr;
	return real_PDR_LightPoint(p);
}

static void draw_text_sample(void)
{
	static const char *lines[] = {
		"The quick brown fox jumps over",
		"the lazy dog. 0123456789",
		"ABCDEFGHIJKLMNOPQRSTUVWXYZ",
		"abcdefghijklmnopqrstuvwxyz",
		"!\"#$%&'()*+,-./:;<=>?@[\\]^_{|}~",
		"You got the Nailgun",
		"You need the silver key",
	};
	int i, y = 24;
	const char *s;

	for (i = 0; i < (int)(sizeof(lines) / sizeof(lines[0])); i++, y += 12)
		for (s = lines[i]; *s; s++)
			Draw_Character(40 + 8 * (int)(s - lines[i]), y, (unsigned char)*s);
	y += 6;
	for (i = 0; i < (int)(sizeof(lines) / sizeof(lines[0])); i++, y += 12)
		for (s = lines[i]; *s; s++)
			Draw_Character(40 + 8 * (int)(s - lines[i]), y, (unsigned char)*s | 128);
}

/* vid_port.c is compiled with VID_Update renamed: the picture modes draw over everything else */
void real_VID_Update(vrect_t *rects);
void VID_Update(vrect_t *rects)
{
	static vrect_t full;

	if (pic_mode != PIC_OFF) {
		Draw_Fill(0, 0, vid.width, vid.height, pic_bg);
		if (pic_mode == PIC_PIC) {
			qpic_t *p = NULL;

			if (!strncmp(pic_name, "wad:", 4))
				p = W_GetLumpName(pic_name + 4);
			else
				p = Draw_CachePic(pic_name);
			if (p && p->width <= (int)vid.width && p->height <= (int)vid.height)
				Draw_TransPic((vid.width - p->width) / 2, (vid.height - p->height) / 2, p);
		} else if (pic_mode == PIC_CHARS) {
			int i, x0 = (vid.width - 16 * 9) / 2, y0 = (vid.height - 16 * 9) / 2;

			for (i = 0; i < 256; i++)
				Draw_Character(x0 + (i & 15) * 9, y0 + (i >> 4) * 9, i);
		} else
			draw_text_sample();
		full.x = full.y = 0;
		full.width = vid.width;
		full.height = vid.height;
		full.pnext = NULL;
		rects = &full;
	}
	real_VID_Update(rects);
}

/* ------------------------------------------------------------------ driver */
static void run(int n)
{
	while (n-- > 0) {
		if (cam_on && sv.active && sv_player) {
			/* the server sends the entities visible from the player: keep the player at the camera */
			/* the eye is view_ofs (22 units) above the origin: the gun is drawn where it belongs */
			VectorCopy(cam_org, sv_player->v.origin);
			sv_player->v.origin[2] -= sv_player->v.view_ofs[2];
			VectorCopy(vec3_origin, sv_player->v.velocity);
			sv_player->v.movetype = MOVETYPE_NOCLIP;
			sv_player->v.flags = (int)sv_player->v.flags | FL_GODMODE | FL_NOTARGET;
			SV_LinkEdict(sv_player, false);
			VectorCopy(cam_ang, cl.viewangles);
		}
		fake_us += 33000;
#ifdef PD_STACK
		pd_stack_top = PD_StackPointer();
#endif
		qembd_frame();
#ifdef PD_STACK
		pd_stack_top = 0;
#endif
	}
}

static void send_frame(void)
{
	static uint8_t out[768 + W * H + 50 * H];
	int y;

	memcpy(out, shot_pal, 768);
	memcpy(out + 768, shot, W * H);
	for (y = 0; y < H; y++)
		memcpy(out + 768 + W * H + y * 50, lcd + y * LCD_ROWSIZE, 50);
	printf("FRAME %d\n", (int)sizeof(out));
	fwrite(out, 1, sizeof(out), stdout);
	fflush(stdout);
}

static void ok(const char *json)
{
	if (json)
		printf("OK %s\n", json);
	else
		printf("OK\n");
	fflush(stdout);
}

static void err(const char *m)
{
	printf("ERR %s\n", m);
	fflush(stdout);
}

static int file_exists(const char *name)
{
	char path[MAX_QPATH];
	int h;

	snprintf(path, sizeof(path), "%s", name);
	if (COM_OpenFile(path, &h) < 0)
		return 0;
	COM_CloseFile(h);
	return 1;
}

static model_t *find_model(const char *name)
{
	if (!file_exists(name))	/* (Mod_ForName would Sys_Error) */
		return NULL;
	return Mod_ForName((char *)name, false);
}

static void load_map(const char *name)
{
	char c[128], buf[512];
	int i;
	entity_t *pl;

	snprintf(c, sizeof(c), "maps/%s.bsp", name);
	if (!file_exists(c)) {
		err("no such map");
		return;
	}
	cam_on = 0;
	ent_on = 0;
	qent.model = NULL;
	key_dest = key_game;
	snprintf(c, sizeof(c), "map %s\n", name);
	Cbuf_AddText(c);
	run(2);
	for (i = 0; i < 600 && !(cls.state == ca_connected && cls.signon == SIGNONS && cl.worldmodel); i++)
		run(1);
	if (!cl.worldmodel) {
		err("map did not load");
		return;
	}
	run(3);
	pl = &cl_entities[cl.viewentity];
	snprintf(buf, sizeof(buf),
			 "{\"origin\":[%g,%g,%g],\"angles\":[%g,%g,%g],\"mins\":[%g,%g,%g],\"maxs\":[%g,%g,%g]}",
			 pl->origin[0], pl->origin[1], pl->origin[2] + 22, cl.viewangles[0], cl.viewangles[1], cl.viewangles[2],
			 cl.worldmodel->mins[0], cl.worldmodel->mins[1], cl.worldmodel->mins[2],
			 cl.worldmodel->maxs[0], cl.worldmodel->maxs[1], cl.worldmodel->maxs[2]);
	ok(buf);
}

static void command(char *line)
{
	char *arg = strchr(line, ' ');
	extern int m_state;

	if (arg)
		*arg++ = 0;
	else
		arg = line + strlen(line);

	if (!strcmp(line, "c")) {
		Cbuf_AddText(arg);
		Cbuf_AddText("\n");
		ok(NULL);
	} else if (!strcmp(line, "run")) {
		run(atoi(arg));
		ok(NULL);
	} else if (!strcmp(line, "frame")) {
		int n = atoi(arg);

		run(n > 0 ? n : 1);
		send_frame();
	} else if (!strcmp(line, "load")) {
		load_map(arg);
	} else if (!strcmp(line, "cam")) {
		if (!strcmp(arg, "off"))
			cam_on = 0;
		else if (sscanf(arg, "%f %f %f %f %f %f", &cam_org[0], &cam_org[1], &cam_org[2],
						&cam_ang[0], &cam_ang[1], &cam_ang[2]) == 6)
			cam_on = 1;
		ok(NULL);
	} else if (!strcmp(line, "ent")) {
		char name[128];
		int frame, skin;
		model_t *m;

		if (!strcmp(arg, "off")) {
			ent_on = 0;
			ok(NULL);
			return;
		}
		memset(&qent, 0, sizeof(qent));
		if (sscanf(arg, "%127s %d %d %f %f %f %f %f %f", name, &frame, &skin, &qent.origin[0], &qent.origin[1],
				   &qent.origin[2], &qent.angles[0], &qent.angles[1], &qent.angles[2]) != 9) {
			err("usage: ent <model> <frame> <skin> x y z pitch yaw roll");
			return;
		}
		if (!cl.worldmodel || !(m = find_model(name))) {
			ent_on = 0;
			err(cl.worldmodel ? "no such model" : "no map loaded");
			return;
		}
		qent.model = m;
		qent.frame = frame;
		qent.skinnum = skin;
		qent.colormap = vid.colormap;
		qent.syncbase = 0;
		ent_on = 1;
		ok(NULL);
	} else if (!strcmp(line, "freeze")) {
		/* Quake's own pause (no "PAUSE" picture: showpause 0): the server stops, the client's clock with it */
		if (sv.active && cls.state == ca_connected && !sv.paused != !atoi(arg))
			Cbuf_AddText("pause\n");
		ok(NULL);
	} else if (!strcmp(line, "solo")) {
		solo = atoi(arg);
		ok(NULL);
	} else if (!strcmp(line, "light")) {
		light_ovr = strcmp(arg, "off") ? atoi(arg) : -1;
		ok(NULL);
	} else if (!strcmp(line, "vmodel")) {
		char name[128];

		vmodel = NULL;
		if (strcmp(arg, "off") && sscanf(arg, "%127s %d", name, &vmodel_frame) == 2 && cl.worldmodel)
			vmodel = find_model(name);
		ok(NULL);
	} else if (!strcmp(line, "ui")) {
		Cbuf_AddText("-showscores\n");
		if (!strcmp(arg, "none")) {
			key_dest = key_game;
			m_state = 0;
		} else if (!strcmp(arg, "console")) {
			m_state = 0;
			key_dest = key_console;
		} else if (!strcmp(arg, "scores")) {
			key_dest = key_game;
			m_state = 0;
			Cbuf_AddText("+showscores\n");
		}
		/* "menu": leave key_dest as the menu_* command set it */
		ok(NULL);
	} else if (!strcmp(line, "pic")) {
		if (!strcmp(arg, "off"))
			pic_mode = PIC_OFF;
		else if (sscanf(arg, "%127s %d", pic_name, &pic_bg) == 2) {
			if (strncmp(pic_name, "wad:", 4) && !file_exists(pic_name)) {
				pic_mode = PIC_OFF;
				err("no such picture");
				return;
			}
			if (!strncmp(pic_name, "wad:", 4)) {
				/* W_GetLumpName is a Sys_Error for a missing lump: check first */
				extern int wad_numlumps;
				extern lumpinfo_t *wad_lumps;
				char clean[16];
				int i;

				W_CleanupName(pic_name + 4, clean);
				for (i = 0; i < wad_numlumps && strcmp(clean, wad_lumps[i].name); i++)
					;
				if (i == wad_numlumps) {
					pic_mode = PIC_OFF;
					err("no such lump");
					return;
				}
			}
			pic_mode = PIC_PIC;
		}
		ok(NULL);
	} else if (!strcmp(line, "chars")) {
		pic_mode = PIC_CHARS;
		pic_bg = atoi(arg);
		ok(NULL);
	} else if (!strcmp(line, "text")) {
		pic_mode = PIC_TEXT;
		pic_bg = atoi(arg);
		ok(NULL);
	} else if (!strcmp(line, "center")) {
		extern float scr_centertime_off;
		char *s;

		if (!strcmp(arg, "off")) {
			scr_centertime_off = 0;
			ok(NULL);
			return;
		}

		for (s = arg; *s; s++)
			if (*s == '|')
				*s = '\n';
		SCR_CenterPrint(arg);
		ok(NULL);
	} else if (!strcmp(line, "info")) {
		char buf[256];

		snprintf(buf, sizeof(buf), "{\"game\":\"%s\",\"map\":%d,\"registered\":%d}", com_gamedir,
				 cl.worldmodel != NULL, (int)registered.value);
		ok(buf);
	} else
		err("unknown command");
}

int main(int argc, char **argv)
{
	static char line[1024];

	gfx.getFrame = get_frame;
	gfx.markUpdatedRows = mark_rows;
	api.graphics = &gfx;
	qembd_pd = &api;
	if (qembd_init(argc, argv) != 0)
		return 1;
	/* no attract-mode demos, no messages over the picture, the console opens at once */
	Cbuf_AddText("stopdemo\ndisconnect\ncon_notifytime 0\nscr_conspeed 100000\nscr_showfps 0\ncrosshair 0\nshowpause 0\n");
	run(2);
	ok("{\"ready\":1}");
	while (fgets(line, sizeof(line), stdin)) {
		size_t n = strlen(line);

		while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
			line[--n] = 0;
		if (n)
			command(line);
	}
	return 0;
}
