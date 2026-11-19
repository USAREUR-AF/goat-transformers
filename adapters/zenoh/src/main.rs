//! goat-xf-pipe-zenoh: `goat-xf-pipe` with the `zenoh:` scheme added.

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    std::process::exit(goat_adapters_std::cli::run("goat-xf-pipe-zenoh", &args, &[&goat_adapters_zenoh::Zenoh]));
}
