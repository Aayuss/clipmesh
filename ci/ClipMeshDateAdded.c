#include <sys/attr.h>
#include <time.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>

int clipmesh_get_date_added(const char *path, int64_t *seconds, int64_t *nanoseconds) {
    if (!path || !seconds || !nanoseconds) {
        errno = EINVAL;
        return -1;
    }

    attrgroup_t requested = ATTR_CMN_RETURNED_ATTRS | ATTR_CMN_ADDEDTIME;
    struct attrlist attrs;
    memset(&attrs, 0, sizeof(attrs));
    attrs.bitmapcount = ATTR_BIT_MAP_COUNT;
    attrs.commonattr = requested;

    typedef struct {
        uint32_t length;
        attribute_set_t returned;
        struct timespec added;
    } __attribute__((aligned(4), packed)) response_t;

    response_t response;
    memset(&response, 0, sizeof(response));
    if (getattrlist(path, &attrs, &response, sizeof(response), 0) != 0) {
        return -1;
    }
    if (response.length != sizeof(response) || response.returned.commonattr != requested) {
        errno = EIO;
        return -1;
    }

    *seconds = (int64_t)response.added.tv_sec;
    *nanoseconds = (int64_t)response.added.tv_nsec;
    return 0;
}

int clipmesh_set_date_added_now(const char *path) {
    if (!path) {
        errno = EINVAL;
        return -1;
    }

    struct timespec now;
    if (clock_gettime(CLOCK_REALTIME, &now) != 0) {
        return -1;
    }

    struct attrlist attrs;
    memset(&attrs, 0, sizeof(attrs));
    attrs.bitmapcount = ATTR_BIT_MAP_COUNT;
    attrs.commonattr = ATTR_CMN_ADDEDTIME;

    typedef struct {
        struct timespec added;
    } __attribute__((aligned(4), packed)) request_t;

    request_t request;
    request.added.tv_sec = now.tv_sec;
    request.added.tv_nsec = now.tv_nsec;

    return setattrlist(path, &attrs, &request, sizeof(request), 0);
}
