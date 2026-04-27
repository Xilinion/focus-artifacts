CC=g++
CFLAGS=-std=c++17 -c -g -O3 -Wall -D SPLINTERDB_PLATFORM_DIR=platform_linux
INCLUDES=-I ../ -I /home/xt253/.local/include
CPPSOURCES=$(wildcard *.cc)
CSOURCES=$(wildcard *.c)
OBJECTS=$(CPPSOURCES:.cc=.o) $(CSOURCES:.c=.o)

all: $(OBJECTS)

.cc.o:
	$(CC) $(CFLAGS) $(INCLUDES) $< -o $@

.c.o:
	$(CC) $(CFLAGS) $(INCLUDES) $< -o $@

clean:
	$(RM) $(OBJECTS)
