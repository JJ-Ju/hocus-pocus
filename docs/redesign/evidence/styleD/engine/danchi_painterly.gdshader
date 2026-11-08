// danchi_painterly.gdshader - round D: the painterly layers as a Godot 4 spatial shader.
// NOT RUN IN GODOT in round D: written from the Houdini MaterialX graphs (apply_painterly.py);
// treat as a recipe to verify. Units are metres, Y up (same as Houdini).
//
// Mesh data (glTF from export_engine.py):
//   COLOR.rgb = 0.5 + (tint - 1) * 2.5      hue drift x sun-facing warmth (decode below)
//   COLOR.a   = sdir                         1 = strokes along the slab, 0 = vertical
//   UV        = the piece's 0-1 UVs (base textures, or the baked painterly set)
//   UV2       = (famp, liftn)                detail amplitude; lift-colour mix
// Textures:
//   strokes / detail: brush_*_engine.png, imported as plain linear data (sRGB off, no
//   normal-map conversion), repeat on. RGB = 0.5 + 0.5 * offset, A = paint height.
//
// Two ways to use it:
//   * runtime world projection (tiling kits): use_world_projection = true; strokes follow
//     world position, so they hold under camera moves and across modular pieces;
//   * baked (unique pieces): bake_piece.py already baked strokes + drift + lift into the
//     piece's albedo / normal / ORM / emissive; set use_t1 = use_t2 = false and plug the maps.
shader_type spatial;
render_mode blend_mix, cull_back, diffuse_burley, specular_schlick_ggx;

uniform sampler2D base_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform float base_roughness = 0.86;
uniform bool use_world_projection = true;
uniform bool use_t1 = true;     // task 1: anime-background brush layer
uniform bool use_t2 = false;    // task 2: hyper-real painterly (Ruan Jia rules)

uniform sampler2D strokes : hint_default_black, filter_linear_mipmap, repeat_enable;
uniform float stroke_tile = 4.0;
uniform float t1_val = 0.03;
uniform float t1_hue_deg = 4.0;
uniform float t1_sat = 0.05;
uniform float t1_temp = 0.010;
uniform float t1_rough = 0.04;

uniform sampler2D detail_tex : hint_default_black, filter_linear_mipmap, repeat_enable;
uniform float detail_tile = 1.5;
uniform float det_val = 0.06;
uniform float det_hue_deg = 12.0;
uniform float det_sat = 0.15;
uniform float det_temp = 0.03;
uniform float det_rough = 0.06;

// lifted, saturated darks (emission); colours are LINEAR values from apply_painterly.P
uniform vec3 lift_cool = vec3(0.35, 0.55, 1.0);
uniform vec3 lift_teal = vec3(0.25, 0.75, 0.85);
uniform vec3 lift_violet = vec3(0.55, 0.40, 1.0);
uniform float lift = 0.04;
uniform float lift_soffit = 1.6;

varying vec3 wpos;
varying vec3 wnrm;

void vertex() {
	wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	wnrm = normalize(mat3(MODEL_MATRIX) * NORMAL);
}

vec3 rgb2hsv(vec3 c) {
	vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
	vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
	vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
	float d = q.x - min(q.w, q.y);
	float e = 1.0e-10;
	return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

vec3 hsv2rgb(vec3 c) {
	vec3 p = abs(fract(c.xxx + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
	return c.z * mix(vec3(1.0), clamp(p - 1.0, 0.0, 1.0), c.y);
}

// the same projection as the MaterialX graph: dominant normal axis, U/V swapped where sdir = 1
vec2 surface_uv(vec3 p, vec3 n, float sdir) {
	vec3 a = abs(n);
	vec2 uv = a.x > a.z ? p.zy : p.xy;
	if (a.y > max(a.x, a.z)) { uv = p.xz; }
	return sdir > 0.5 ? uv.yx : uv;
}

vec3 stroke_mod(vec3 col, vec4 s, float val, float hue_deg, float sat, float temp, float amp) {
	vec3 o = (s.rgb * 2.0 - 1.0) * amp;           // per-stroke value, hue, saturation offsets
	vec3 h = rgb2hsv(col);
	h.x = fract(h.x + o.g * hue_deg / 360.0);
	h.y *= 1.0 + o.b * sat;
	h.z *= 1.0 + o.r * val;
	float t = o.g * temp;                         // temperature tilt so greys shift too
	return hsv2rgb(h) * vec3(1.0 + t, 1.0, 1.0 - t);
}

void fragment() {
	vec3 col = texture(base_albedo, UV).rgb;
	float rough = base_roughness;
	vec2 puv = surface_uv(wpos, wnrm, COLOR.a);
	if (use_world_projection && use_t1) {
		vec4 s = texture(strokes, puv / stroke_tile);
		col = stroke_mod(col, s, t1_val, t1_hue_deg, t1_sat, t1_temp, 1.0);
		rough -= t1_rough * (s.a - 0.8);
	}
	if (use_t2) {
		col *= 1.0 + (COLOR.rgb - 0.5) * 0.4;         // hue drift and sun warmth (vertex colour)
		float famp = UV2.x;
		if (use_world_projection) {
			vec4 d = texture(detail_tex, puv / detail_tile);
			col = stroke_mod(col, d, det_val, det_hue_deg, det_sat, det_temp, famp);
			rough -= det_rough * (d.a * famp - 0.8);
		}
		float n3 = UV2.y;
		vec3 a1 = mix(lift_cool, lift_teal, smoothstep(0.5, 0.85, n3));
		vec3 lc = mix(a1, lift_violet, 1.0 - smoothstep(0.1, 0.35, n3));
		float soff = mix(1.0, lift_soffit, smoothstep(0.3, 0.8, -wnrm.y));
		float lum = dot(col, vec3(0.2126, 0.7152, 0.0722));
		EMISSION = lc * lum * (lift / 0.5) * soff;   // standard emissive output
	}
	ALBEDO = col;
	ROUGHNESS = clamp(rough, 0.05, 1.0);
	// Stroke relief: on baked pieces use the baked normal map. For world projection, a
	// height-derived normal needs a world-to-tangent transform; left out here (faint, 1.5-2 mm).
}

// Optional, true light/shadow hue split (needs a runtime shader; uncomment to use, and remove
// the sun-facing factor from the vertex tint). light() replaces Godot's built-in lighting, so
// both diffuse and specular must be written.
// uniform vec3 key_warm = vec3(1.035, 1.0, 0.955);
// uniform vec3 shadow_cool = vec3(0.96, 1.0, 1.06);
// void light() {
//     float ndl = clamp(dot(NORMAL, LIGHT), 0.0, 1.0);
//     float lit = ndl * ATTENUATION;                          // ATTENUATION carries the shadow map
//     vec3 tint = mix(shadow_cool, key_warm, smoothstep(0.0, 0.4, lit));
//     DIFFUSE_LIGHT += lit * LIGHT_COLOR / PI * tint;
//     vec3 H = normalize(VIEW + LIGHT);
//     float spec = pow(clamp(dot(NORMAL, H), 0.0, 1.0), mix(8.0, 64.0, 1.0 - ROUGHNESS));
//     SPECULAR_LIGHT += spec * lit * LIGHT_COLOR * 0.04;
// }
