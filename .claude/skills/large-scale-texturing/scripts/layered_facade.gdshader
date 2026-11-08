// layered_facade.gdshader - Godot 4 spatial shader: a weathered facade from shared tiling sets and
// this facade's low-res masks, the way scripts/weathering/wx_hires.py composes it in numpy.
//
// Not yet run in Godot on this machine (no engine here): check it against a numpy crop (T8 in the
// skill) before relying on it.
//
//  - Base: the coat's tiling albedo (hex-tiled: no tile period shows) under the wall colour.
//  - Masks (planar projection in facade metres): M_hi 50 px/m (R run-off, G stains and splash, B growth,
//    A light layers), M_lo 25 px/m (R film, G damp, B coat tone, A edge wear), the dirt tint, the
//    growth stage and its colour ramp.
//  - Each mask is revealed against its own tiling detail field (stored Gaussian: texel = 0.5 + g / 8)
//    with the edge rule; past far_m the mask alone decides, so the amounts the gate measured hold at
//    every distance.
//  - Run-off detail is offset per vertical band and never rotated, so no seam cuts a streak.
shader_type spatial;
render_mode blend_mix, depth_draw_opaque, cull_back, diffuse_burley, specular_schlick_ggx;

// ---- shared tiling sets (sizes in metres, from shader_contract.json)
uniform sampler2D coat_albedo : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D coat_normal : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform float coat_tile_m = 3.6;
uniform float coat_cell_m = 1.2;
uniform sampler2D micro_g : filter_linear_mipmap, repeat_enable;    // coat relief, Gaussian (troughs low)
uniform float micro_tile_m = 0.6;
uniform float micro_cell_m = 0.2;
uniform sampler2D grime_g : filter_linear_mipmap, repeat_enable;
uniform sampler2D stain_g : filter_linear_mipmap, repeat_enable;
uniform sampler2D splash_g : filter_linear_mipmap, repeat_enable;
uniform sampler2D growth_g : filter_linear_mipmap, repeat_enable;
uniform sampler2D runoff_g : filter_linear_mipmap, repeat_enable;   // 1.024 x 4.096 m, vertical rivulets
uniform float detail_tile_m = 1.024;
uniform vec2 runoff_tile_m = vec2(1.024, 4.096);

// ---- this facade
uniform sampler2D m_hi : filter_linear_mipmap, repeat_disable;
uniform sampler2D m_lo : filter_linear_mipmap, repeat_disable;
uniform sampler2D dirt_tint : source_color, filter_linear_mipmap, repeat_disable;
uniform sampler2D growth_stage : filter_linear_mipmap, repeat_disable;
uniform sampler2D growth_ramp : source_color, filter_linear, repeat_disable;
uniform vec3 facade_origin;                   // world position of the plane's top-left corner
uniform vec3 facade_u = vec3(1.0, 0.0, 0.0);  // unit: right along the facade
uniform vec3 facade_v = vec3(0.0, -1.0, 0.0); // unit: down the facade
uniform vec2 facade_size_m = vec2(81.92, 36.28);
uniform vec3 wall_colour : source_color = vec3(0.85, 0.84, 0.80);

// ---- the contract's constants
uniform float near_m = 8.0;       // nearer than this the detail decides the edges
uniform float far_m = 25.0;       // farther than this the mask alone (mean kept)
uniform float film_k = 0.40;      // film modulation by grime and troughs
uniform float film_rec = 0.75;    // share of the coat's troughs in the film's detail
uniform float w_stain = 0.60;
uniform float w_splash = 0.45;
uniform float w_run = 0.55;
uniform float w_growth = 0.30;
uniform float w_light = 0.30;
uniform float run_band_m = 0.35;
// The mark colours are LINEAR values (weather_fields.COL), so they carry no source_color hint: Godot
// converts source_color uniforms from sRGB, which made them about 10x too dark (0.094 -> 0.009).
// wall_colour above is sRGB-encoded and keeps its hint.
uniform vec3 k_film = vec3(0.094, 0.076, 0.052);   // linear
uniform vec3 k_stain = vec3(0.084, 0.069, 0.050);  // linear
uniform vec3 k_run = vec3(0.074, 0.060, 0.042);    // linear
uniform vec3 k_light = vec3(0.78, 0.78, 0.75);     // linear
uniform float rough_coat = 0.88;
uniform float rough_damp = 0.25;

varying vec3 world_pos;

void vertex() {
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

// integer hash of a lattice vertex to [0,1)^2 (same constants as wx_detail.hash_u32)
vec2 hash2(vec2 ij, float salt) {
	uvec2 q = uvec2(ivec2(ij));
	uint x = (q.x * 0x8DA6B343u) ^ (q.y * 0xD8163841u) ^ uint(salt);
	x ^= x >> 16u; x *= 0x7FEB352Du; x ^= x >> 15u; x *= 0x846CA68Bu; x ^= x >> 16u;
	uint y = x ^ 0x5BD1E995u;
	y ^= y >> 16u; y *= 0x7FEB352Du; y ^= y >> 15u; y *= 0x846CA68Bu; y ^= y >> 16u;
	return vec2(float(x), float(y)) / 4294967296.0;
}

// triangle grid (Heitz and Neyret 2018): three vertices and barycentric weights
void tri_grid(vec2 p, out vec2 v1, out vec2 v2, out vec2 v3, out vec3 w) {
	vec2 s = vec2(p.x - 0.57735027 * p.y, 1.15470054 * p.y);    // equilateral lattice (Heitz and Neyret 2018)
	vec2 b = floor(s);
	vec2 f = s - b;
	float z = 1.0 - f.x - f.y;
	if (z > 0.0) {
		w = vec3(z, f.y, f.x); v1 = b; v2 = b + vec2(0.0, 1.0); v3 = b + vec2(1.0, 0.0);
	} else {
		w = vec3(-z, 1.0 - f.y, 1.0 - f.x); v1 = b + vec2(1.0); v2 = b + vec2(1.0, 0.0); v3 = b + vec2(0.0, 1.0);
	}
}

// standard normal CDF (tanh approximation, |err| < 2e-4)
float phi(float x) {
	return 0.5 * (1.0 + tanh(0.7978845608 * (x + 0.044715 * x * x * x)));
}

// histogram-preserving hex-tiled sample of a Gaussian detail field, rotated per vertex
float hex_g(sampler2D t, vec2 f, float tile_m, float cell_m, float salt) {
	vec2 v1; vec2 v2; vec2 v3; vec3 w;
	tri_grid(f / cell_m, v1, v2, v3, w);
	w = w * w;                                   // sharpness 2
	float g = 0.0;
	vec2 vs[3] = vec2[](v1, v2, v3);
	for (int i = 0; i < 3; i++) {
		vec2 h = hash2(vs[i], salt);
		float th = hash2(vs[i], salt + 7.0).x * 6.2831853;
		mat2 r = mat2(vec2(cos(th), sin(th)), vec2(-sin(th), cos(th)));
		vec2 uv = (r * f) / tile_m + h;
		g += w[i] * (texture(t, uv).r - 0.5) * 8.0;
	}
	return g / sqrt(max(dot(w, w), 1e-6));
}

// run-off rivulets: offsets per vertical band, blended across bands only, never rotated
float band_g(sampler2D t, vec2 f, vec2 tile_m, float band_m, float salt) {
	float b = f.x / band_m;
	float i0 = floor(b);
	float tt = b - i0;
	float g = 0.0;
	float den = 0.0;
	for (int k = 0; k < 2; k++) {
		float i = i0 + float(k);
		float w = (k == 0) ? (1.0 - tt) : tt;
		w = w * w;
		vec2 h = hash2(vec2(i, 0.0), salt);
		float flip = hash2(vec2(i, 0.0), salt + 3.0).x < 0.5 ? -1.0 : 1.0;
		vec2 uv = vec2(flip * f.x, f.y) / tile_m + h;
		g += w * (texture(t, uv).r - 0.5) * 8.0;
		den += w * w;
	}
	return g / sqrt(max(den, 1e-6));
}

vec3 hex_rgb(sampler2D t, vec2 f, float tile_m, float cell_m, float salt) {
	vec2 v1; vec2 v2; vec2 v3; vec3 w;
	tri_grid(f / cell_m, v1, v2, v3, w);
	vec2 vs[3] = vec2[](v1, v2, v3);
	vec3 c = vec3(0.0);
	float sum = 0.0;
	for (int i = 0; i < 3; i++) {
		vec3 s = texture(t, f / tile_m + hash2(vs[i], salt)).rgb;
		float wi = pow(w[i], 7.0) * (0.4 + 0.6 * dot(s, vec3(0.2126, 0.7152, 0.0722)));
		c += wi * s;
		sum += wi;
	}
	return c / max(sum, 1e-6);
}

// the edge rule: a coarse alpha a whose local opacity is pk becomes spots of pk where the detail u
// is above 1 - a / pk (coverage kept); far away the mask alone
float reveal(float a, float pk, float u, float w, float fd) {
	float m = clamp(a / max(pk, 1e-4), 0.0, 1.0);
	float hw = max(min(min(0.5 * w, m), 1.0 - m), 5e-5);   // half-width narrows at m = 0 and 1: zero stays zero
	float near = pk * clamp((u - (1.0 - m)) / (2.0 * hw) + 0.5, 0.0, 1.0);
	return mix(near, a, fd);
}

void fragment() {
	vec3 rel = world_pos - facade_origin;
	vec2 f = vec2(dot(rel, facade_u), dot(rel, facade_v));          // facade metres
	vec2 uv = f / facade_size_m;
	vec4 Mh = texture(m_hi, uv);
	vec4 Ml = texture(m_lo, uv);
	vec3 T = texture(dirt_tint, uv).rgb;
	float stage = texture(growth_stage, uv).r;
	float dist = length(world_pos - CAMERA_POSITION_WORLD);
	float fd = clamp((dist - near_m) / (far_m - near_m), 0.0, 1.0);

	vec3 A = wall_colour * hex_rgb(coat_albedo, f, coat_tile_m, coat_cell_m, 11.0) / 0.68;
	A *= 1.0 + 0.2 * (Ml.b - 0.5);                                      // coat tone: fading, repaint
	float rec = -hex_g(micro_g, f, micro_tile_m, micro_cell_m, 13.0);   // troughs high

	// film: a mean-kept modulation by grime and the coat's troughs
	float gf = (film_rec * rec + (1.0 - film_rec) * hex_g(grime_g, f, detail_tile_m, 0.30, 17.0)) /
	           sqrt(film_rec * film_rec + (1.0 - film_rec) * (1.0 - film_rec));
	float a_film = Ml.r * max(1.0 + film_k * gf * (1.0 - fd), 0.0);
	A = mix(A, T * (k_film / 0.09), a_film);
	// stains and the ground band (one channel): revealed against the stain and splash fields
	float pk = clamp(Mh.g * 1.6, 0.05, 1.0);
	float us = phi(0.55 * rec + 0.84 * hex_g(stain_g, f, 2.048, 0.45, 19.0));
	A = mix(A, T * (k_stain / 0.08), reveal(Mh.g, pk, us, w_stain, fd));
	// run-off: the streak envelope revealed against vertical rivulets
	float ur = phi(band_g(runoff_g, f, runoff_tile_m, run_band_m, 23.0));
	A = mix(A, T * (k_run / 0.07), reveal(Mh.r, clamp(Mh.r * 1.6, 0.05, 1.0), ur, w_run, fd));
	// growth: its own colony field; colour from the continuum at this place's stage
	float ug = phi(0.45 * rec + 0.89 * hex_g(growth_g, f, detail_tile_m, 0.30, 29.0));
	vec3 kg = texture(growth_ramp, vec2(stage, 0.5)).rgb;
	float a_g = reveal(Mh.b, clamp(Mh.b * 1.6, 0.05, 1.0), ug, w_growth, fd);
	vec3 Ag = mix(A, kg, a_g);
	A = (dot(Ag, vec3(0.2126, 0.7152, 0.0722)) > dot(A, vec3(0.2126, 0.7152, 0.0722))) ? A : Ag;   // growth never lightens
	// light layers (efflorescence) on the coat's peaks
	A = mix(A, k_light, reveal(Mh.a, clamp(Mh.a * 1.6, 0.05, 1.0), phi(-rec), w_light, fd));

	ALBEDO = A;
	ROUGHNESS = clamp(rough_coat - rough_damp * Ml.g, 0.05, 1.0);
	NORMAL_MAP = texture(coat_normal, f / coat_tile_m).rgb;
}
