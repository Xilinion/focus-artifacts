CC=g++
CFLAGS=-std=c++17 -c -g -O3 -Wall -D SPLINTERDB_PLATFORM_DIR=platform_linux
INCLUDES=-I ../ -I /home/xt253/.local/include
SOURCES=$(filter-out rocks_db.cc transaction_rocks_db.cc optimistic_transaction_rocks_db.cc redis_db.cc, $(wildcard *.cc))
OBJECTS=$(SOURCES:.cc=.o)

all: $(SOURCES) $(OBJECTS)

.cc.o:
	$(CC) $(CFLAGS) $(INCLUDES) $< -o $@

clean:
	$(RM) $(OBJECTS)

