CC=g++
CFLAGS=-std=c++17 -g -Wall -pthread -I./ -I/home/xt253/.local/include -D SPLINTERDB_PLATFORM_DIR=platform_linux
LDFLAGS= -lpthread -ltbb -lsplinterdb -lnuma -L/home/xt253/.local/lib -Wl,-rpath,/home/xt253/.local/lib
SUBDIRS=core db
SUBCPPSRCS=$(wildcard core/*.cc) $(filter-out db/rocks_db.cc db/transaction_rocks_db.cc db/optimistic_transaction_rocks_db.cc db/redis_db.cc, $(wildcard db/*.cc))
SUBCSRCS=$(wildcard core/*.c) $(wildcard db/*.c)
OBJECTS=$(SUBCPPSRCS:.cc=.o) $(SUBCSRCS:.c=.o)
EXEC=ycsbc

all: $(SUBDIRS) $(EXEC)

$(SUBDIRS):
	$(MAKE) -C $@

$(EXEC): $(wildcard *.cc) $(OBJECTS)
	$(CC) $(CFLAGS) $^ $(LDFLAGS) -o $@

clean:
	for dir in $(SUBDIRS); do \
		$(MAKE) -C $$dir $@; \
	done
	$(RM) $(EXEC)

.PHONY: $(SUBDIRS) $(EXEC)

