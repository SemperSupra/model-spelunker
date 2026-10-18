/* Public-safe, source-known Windows x64 FID/BSim reference and false-match control.
 * No CRT, dynamic imports, secrets, or third-party/vendored binary input.
 */
#if defined(_MSC_VER)
#define KEEP __declspec(noinline)
#elif defined(__clang__) || defined(__GNUC__)
#define KEEP __attribute__((noinline, used))
#else
#define KEEP
#endif
typedef unsigned int u32;
KEEP u32 re_lib_mix(u32 v) {
    v ^= 0x47ac123bu;
    v *= 0x9e3779b1u;
    return (v << 11) | (v >> 21);
}
KEEP u32 re_lib_crc(u32 v) {
    for (u32 i = 0; i < 16; ++i)
        v = (v >> 1) ^ ((0u - (v & 1u)) & 0xedb88320u);
    return v;
}
KEEP u32 re_lib_scramble(u32 v) {
    for (u32 i = 0; i < 8; ++i)
        v = re_lib_mix(v + (0x1000193u * i)) ^ (v >> 3);
    return v;
}
/* Exported only by labeled reference; not reachable in optimized target DLL. */
KEEP u32 re_lib_unrelated(u32 v) {
    for (u32 i = 0; i < 12; ++i)
        v = v * 37u + (v ^ i);
    return v;
}
__declspec(dllexport) KEEP u32 re_dispatch(u32 kind, u32 v) {
    if (kind == 5) return re_lib_crc(v) ^ 0x11223344u;
    if (kind == 7) return re_lib_mix(v) + 3u;
    if (kind == 9) return re_lib_scramble(v);
    return 0xffffffffu;
}
