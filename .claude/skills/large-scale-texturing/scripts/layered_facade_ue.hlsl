// layered_facade_ue.hlsl - Unreal Engine 5 Custom-node functions for the weathered facade, the same
// stack as layered_facade.gdshader and scripts/weathering/wx_hires.py.
//
// Not yet run in Unreal on this machine (no engine here): check it against a numpy crop (T8 in the
// skill) before relying on it.
//
// Use: put this file under <Project>/Shaders/ and add a virtual shader path in a plugin or module,
// or paste the functions into one Custom node's "Include File Paths" target. One Custom node per
// layer calls WX_Reveal / WX_HexG / WX_BandG with Texture2D + SamplerState inputs named as below.
// Masks are sampled by planar projection: f = facade metres from the plane's top-left corner along
// its right (U) and down (V) axes; uv = f / FacadeSizeM.

float2 WX_Hash2(float2 ij, uint salt)
{
    uint2 q = (uint2)(int2)ij;
    uint x = (q.x * 0x8DA6B343u) ^ (q.y * 0xD8163841u) ^ salt;
    x ^= x >> 16; x *= 0x7FEB352Du; x ^= x >> 15; x *= 0x846CA68Bu; x ^= x >> 16;
    uint y = x ^ 0x5BD1E995u;
    y ^= y >> 16; y *= 0x7FEB352Du; y ^= y >> 15; y *= 0x846CA68Bu; y ^= y >> 16;
    return float2(x, y) / 4294967296.0;
}

// triangle grid (Heitz and Neyret 2018)
void WX_TriGrid(float2 p, out float2 v1, out float2 v2, out float2 v3, out float3 w)
{
    float2 s = float2(p.x - 0.57735027 * p.y, 1.15470054 * p.y);    // equilateral lattice (Heitz and Neyret 2018)
    float2 b = floor(s);
    float2 f = s - b;
    float z = 1.0 - f.x - f.y;
    if (z > 0.0) { w = float3(z, f.y, f.x); v1 = b; v2 = b + float2(0, 1); v3 = b + float2(1, 0); }
    else { w = float3(-z, 1.0 - f.y, 1.0 - f.x); v1 = b + 1.0; v2 = b + float2(1, 0); v3 = b + float2(0, 1); }
}

float WX_Phi(float x)            // standard normal CDF, |err| < 2e-4
{
    return 0.5 * (1.0 + tanh(0.7978845608 * (x + 0.044715 * x * x * x)));
}

// histogram-preserving hex-tiled sample of a Gaussian detail field (texel = 0.5 + g / 8)
float WX_HexG(Texture2D T, SamplerState S, float2 f, float tileM, float cellM, uint salt)
{
    float2 v[3]; float3 w;
    WX_TriGrid(f / cellM, v[0], v[1], v[2], w);
    w = w * w;
    float g = 0;
    [unroll] for (int i = 0; i < 3; i++)
    {
        float2 h = WX_Hash2(v[i], salt);
        float th = WX_Hash2(v[i], salt + 7u).x * 6.2831853;
        float2 r = float2(cos(th) * f.x - sin(th) * f.y, sin(th) * f.x + cos(th) * f.y);
        g += w[i] * (T.Sample(S, r / tileM + h).r - 0.5) * 8.0;
    }
    return g / sqrt(max(dot(w, w), 1e-6));
}

// run-off rivulets: offsets per vertical band, blended across bands only, never rotated
float WX_BandG(Texture2D T, SamplerState S, float2 f, float2 tileM, float bandM, uint salt)
{
    float b = f.x / bandM;
    float i0 = floor(b);
    float t = b - i0;
    float g = 0, den = 0;
    [unroll] for (int k = 0; k < 2; k++)
    {
        float i = i0 + k;
        float w = k == 0 ? 1.0 - t : t;
        w *= w;
        float2 h = WX_Hash2(float2(i, 0), salt);
        float flip = WX_Hash2(float2(i, 0), salt + 3u).x < 0.5 ? -1.0 : 1.0;
        g += w * (T.Sample(S, float2(flip * f.x, f.y) / tileM + h).r - 0.5) * 8.0;
        den += w * w;
    }
    return g / sqrt(max(den, 1e-6));
}

// the edge rule: coverage kept, the mask alone far away (fd = saturate((dist - near) / (far - near)))
float WX_Reveal(float a, float pk, float u, float w, float fd)
{
    float m = saturate(a / max(pk, 1e-4));
    float hw = max(min(min(0.5 * w, m), 1.0 - m), 5e-5);   // half-width narrows at m = 0 and 1: zero stays zero
    float nearV = pk * saturate((u - (1.0 - m)) / (2.0 * hw) + 0.5);
    return lerp(nearV, a, fd);
}

// Material graph, per pixel (constants from shader_contract.json):
//   f   = float2(dot(P - Origin, U), dot(P - Origin, V));  uv = f / FacadeSizeM
//   Mh  = M_hi(uv); Ml = M_lo(uv); Tn = Tint(uv); stage = Stage(uv); fd = saturate((d - 8) / 17)
//   A   = WallColour * HexRGB(CoatAlbedo, f) * (1 + 0.2 * (Ml.b - 0.5))
//   rec = -WX_HexG(MicroG, f, 0.6, 0.2, 13)
//   film: A = lerp(A, Tn * kFilm, Ml.r * max(1 + 0.40 * (0.75 rec + 0.25 grime) / 0.79 * (1 - fd), 0))
//   stains+splash: A = lerp(A, Tn * kStain, WX_Reveal(Mh.g, saturate(1.6 Mh.g), Phi(0.55 rec + 0.84 stainG), 0.60, fd))
//   run-off: A = lerp(A, Tn * kRun, WX_Reveal(Mh.r, saturate(1.6 Mh.r), Phi(WX_BandG(RunoffG, f, (1.024, 4.096), 0.35, 23)), 0.55, fd))
//   growth: kg = GrowthRamp(stage); A = darker of (A, lerp(A, kg, WX_Reveal(Mh.b, ..., Phi(0.45 rec + 0.89 growthG), 0.30, fd)))
//   light: A = lerp(A, kLight, WX_Reveal(Mh.a, ..., Phi(-rec), 0.30, fd))
//   Roughness = 0.88 - 0.25 * Ml.g
