/* Minimal numa.h stub — real libnuma is available at runtime via -lnuma */
#pragma once
#ifdef __cplusplus
extern "C" {
#endif
int numa_num_configured_cpus(void);
int numa_num_configured_nodes(void);
#ifdef __cplusplus
}
#endif
