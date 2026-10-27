/* Synthetic source-known dispatcher for portable object-format RE qualification.
 * Freestanding C; no runtime, external libraries, or private target material.
 * Outputs are objects only, NOT native runnable apps for target operating systems.
 */
typedef unsigned int u32;

#if defined(__GNUC__) || defined(__clang__)
#define KEEP __attribute__((used, noinline))
#else
#define KEEP
#endif

KEEP u32 handler_affine(u32 value) {
    return (value * 33u) ^ 0x5a5a5a5au;
}

KEEP u32 handler_rotate(u32 value) {
    return (value << 7) | (value >> 25);
}

KEEP u32 handler_fold(u32 value) {
    u32 out = 0x7f4a7c15u;
    for (u32 i = 0; i < 4u; ++i) {
        out = ((out << 3) | (out >> 29)) ^ (value + i * 17u);
    }
    return out;
}

KEEP u32 command_dispatch(u32 command, u32 value) {
    switch (command) {
        case 0x11u: return handler_affine(value) + 17u;
        case 0x29u: return handler_rotate(value) ^ 0xa55a0ff0u;
        case 0x3du: return handler_fold(value);
        default: return 0xffffffffu;
    }
}
