/* i2c_hammer.c
 * Continuously reads WHO_AM_I (0x0F) from a sensor at /dev/i2c-<bus> addr <addr>.
 * Used as I2C bus contention source for the v7.5 stress condition (pre-reg amendment).
 *
 * Usage: i2c_hammer <bus> <addr>
 *   bus: e.g. 7
 *   addr: e.g. 0x6a (LSM6DSOX on this rig)
 *
 * Runs until killed by SIGINT/SIGTERM/SIGKILL.
 */
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <bus> <addr>\n", argv[0]);
        return 2;
    }
    int bus = atoi(argv[1]);
    int addr = (int) strtol(argv[2], NULL, 0);  /* supports 0x prefix */

    char path[64];
    snprintf(path, sizeof(path), "/dev/i2c-%d", bus);
    int fd = open(path, O_RDWR);
    if (fd < 0) {
        perror("open");
        return 1;
    }
    if (ioctl(fd, I2C_SLAVE, addr) < 0) {
        perror("I2C_SLAVE");
        close(fd);
        return 1;
    }

    /* Loop: write 0x0F, read 1 byte. */
    unsigned char reg = 0x0F;
    unsigned char value;
    while (1) {
        if (write(fd, &reg, 1) != 1) {
            /* Transient errors expected under contention; ignore and continue */
            continue;
        }
        if (read(fd, &value, 1) != 1) {
            continue;
        }
    }
    close(fd);
    return 0;
}
