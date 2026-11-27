# sbp-linux-var

The messages of the SBP package `swiftnav.sbp.linux` whose payload length is not fixed, as one
`layout sequential` pack written by `tools/gen/sbp2pack.py` from libsbp v6.5.2 (commit 925825dea5174f069b5d6e23548f213e09f0235c).
The messages of fixed length are in `sbp-linux`. Each kind is selected by the message type;
the payload is a `length 8 bytes` extent. An array or a text that runs to the end of
the frame is a `rest` group (a text one byte per item), and an array counted by an
earlier field is a group counted by it, whose line is then the count (engine-spec 0.21).
No field binds a shared key. The CRC is left to a framer.

A text that runs to the end of the frame is a list of byte values, not one text key:
the pack language has no text field whose length is what remains of its extent, so
a model check can test single bytes but not the text as a whole.

| Kind | Message | Id | Lines |
|---|---|---:|---:|
| `linux_cpu_state_dep_a` | MSG_LINUX_CPU_STATE_DEP_A | 32512 | 7 |
| `linux_mem_state_dep_a` | MSG_LINUX_MEM_STATE_DEP_A | 32513 | 7 |
| `linux_process_socket_counts` | MSG_LINUX_PROCESS_SOCKET_COUNTS | 32515 | 8 |
| `linux_process_socket_queues` | MSG_LINUX_PROCESS_SOCKET_QUEUES | 32516 | 10 |
| `linux_process_fd_count` | MSG_LINUX_PROCESS_FD_COUNT | 32518 | 6 |
| `linux_process_fd_summary` | MSG_LINUX_PROCESS_FD_SUMMARY | 32519 | 4 |
| `linux_cpu_state` | MSG_LINUX_CPU_STATE | 32520 | 9 |
| `linux_mem_state` | MSG_LINUX_MEM_STATE | 32521 | 9 |

8 round-trip vectors `rt-*`, written by the generator's serializer from the definitions; each
group holds two items. Vectors `derived-*` were derived by hand from the definitions,
independently of the generator and of every engine; the generator keeps them.

Do not edit `pack.def`, `PROVENANCE.md`, the module or the vectors by hand: change the
generator or its inputs and run it again.
