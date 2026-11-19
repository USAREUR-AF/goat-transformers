//! goat-adapters-std: the transports the standard library can reach.
//!
//! Standard input and output, files and directories, TCP, UDP (unicast and
//! multicast) and serial ports opened as device files. No third-party crate.
//!
//! - [`uri`] reads an endpoint such as `udp://:4242` and opens it.
//! - [`io`] holds the sources and sinks.
//! - [`cli`] is the `goat-xf-pipe` command line, as a function, so that an
//!   adapter crate with a dependency can add its scheme and reuse the rest.

pub mod cli;
pub mod io;
pub mod uri;
