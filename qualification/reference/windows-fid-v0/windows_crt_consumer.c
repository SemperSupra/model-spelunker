/* Source-known CRT linkage probe for native MSVC /MT versus /MD.
 * Never execute this PE in hosted qualification. Tests provenance/linkage only.
 */
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
static int __cdecl re_compare_ints(const void *a, const void *b) {
    int x = *(const int *)a, y = *(const int *)b;
    return (x > y) - (x < y);
}
__declspec(dllexport) int re_crt_dispatch(const char *text) {
    int items[] = {31, 7, 53, 2, 91, 17, 6, 41};
    unsigned long long number;
    if (text == NULL) return -1;
    number = _strtoui64(text, NULL, 10);
    qsort(items, sizeof(items) / sizeof(items[0]), sizeof(items[0]), re_compare_ints);
    return (int)((number & 0x7fffULL) + (unsigned int)items[0] + strlen(text));
}
int main(int argc, char **argv) {
    return re_crt_dispatch(argc > 1 ? argv[1] : "12") & 255;
}
