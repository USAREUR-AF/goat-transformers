//! goat-xf-pipe-mqtt: `goat-xf-pipe` with the `mqtt://` scheme added.

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    std::process::exit(goat_adapters_std::cli::run("goat-xf-pipe-mqtt", &args, &[&goat_adapters_mqtt::Mqtt]));
}
