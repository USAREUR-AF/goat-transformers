//! goat-xf-pipe: messages arrive on one endpoint, leave converted on others.
//! `goat-xf-pipe --help` prints the options.

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    std::process::exit(goat_adapters_std::cli::run("goat-xf-pipe", &args, &[]));
}
