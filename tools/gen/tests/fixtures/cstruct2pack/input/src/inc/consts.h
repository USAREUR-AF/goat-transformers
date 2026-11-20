/* Synthetic header written for the cstruct2pack tests. */
#ifndef CONSTS_H
#define CONSTS_H
#define NAME_LEN        8
#define LONG_N          (64 + 6)
#ifdef SOME_OPTION
#define ROWS            9
#else
#define ROWS            2
#endif
enum { MODE_A, MODE_B = 4, MODE_C };
#endif
