# prog

hw-lab 三只下载器的唯一入口。板子自己的熔丝、分区擦除和 `openocd.cfg` 仍留在各固件目录。

```
prog list
prog openocd nanodap -- -f <board>/openocd.cfg -c "program <elf> verify reset exit"
prog openocd stlink  -- -f <board>/openocd.cfg -c "program <elf> verify reset exit"
prog avrdude -- -p t13 -U flash:w:<hex>:i
```

| 名字 | 硬件 | 实际调用 |
| --- | --- | --- |
| `nanodap` | nanoDAP（CMSIS-DAP） | OpenOCD `interface/cmsis-dap.cfg` |
| `stlink` | STM32F429-DISC1 板载 ST-LINK | OpenOCD `interface/stlink.cfg` |
| `asp` | ASP（USBasp） | `avrdude -c usbasp` |

已有板子直接跑该板的 `flash.sh`。不要绕过本工具去调 `openocd` 或 `avrdude`。
