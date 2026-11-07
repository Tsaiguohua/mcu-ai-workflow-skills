#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum { FRAME_SIZE = 4 };

struct parser {
    uint8_t frame[FRAME_SIZE];
    size_t used;
};

static int digit(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int on_rx_chunk(struct parser *state, const char *hex)
{
    size_t length = strlen(hex);
    if (length == 0 || length % 2 != 0) return 1;
#if !KEEP_PARTIAL
    state->used = 0; /* Old behavior: forget a partial frame at each read. */
#endif
    for (size_t i = 0; i < length; i += 2) {
        int hi = digit(hex[i]), lo = digit(hex[i + 1]);
        if (hi < 0 || lo < 0) return 1;
        state->frame[state->used++] = (uint8_t)((hi << 4) | lo);
        if (state->used == FRAME_SIZE) {
            for (size_t j = 0; j < FRAME_SIZE; ++j)
                printf("%02x", (unsigned)state->frame[j]);
            putchar('\n');
            state->used = 0;
        }
    }
    return 0;
}

int main(int argc, char **argv)
{
    struct parser state = {0};
    for (int i = 1; i < argc; ++i)
        if (on_rx_chunk(&state, argv[i])) return 2;
    return 0;
}
