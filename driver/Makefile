obj-m += imx708.o
KDIR ?= /usr/src/linux-headers-6
all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules
clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
