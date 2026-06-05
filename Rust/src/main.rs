use std::cmp::Ordering;
use std::env;
use std::fs;
use std::io::{self, Write};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpStream};
use std::path::PathBuf;
use std::time::{Duration, Instant};

#[derive(Debug, Clone)]
struct ScanConfig {
    max_ip: usize,
    max_latency_ms: u128,
    attempts: usize,
    connect_timeout_ms: u64,
    input_file: PathBuf,
}

impl Default for ScanConfig {
    fn default() -> Self {
        Self {
            max_ip: 10,
            max_latency_ms: 1_000,
            attempts: 4,
            connect_timeout_ms: 1_000,
            input_file: PathBuf::from("../ipv4.txt"),
        }
    }
}

#[derive(Debug, Clone)]
struct ScanResult {
    ip: IpAddr,
    latency_ms: u128,
    jitter_ms: u128,
    loss_percent: f64,
    reachable: bool,
}

impl ScanResult {
    fn score(&self) -> f64 {
        if !self.reachable {
            return f64::MAX;
        }
        self.latency_ms as f64 + self.jitter_ms as f64 + (self.loss_percent * 10.0)
    }
}

#[derive(Debug, Clone, Copy)]
struct Ipv4Cidr {
    network: Ipv4Addr,
    prefix: u8,
}

impl Ipv4Cidr {
    fn parse(raw: &str) -> Option<Self> {
        let trimmed = raw.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            return None;
        }
        let (ip_raw, prefix) = match trimmed.split_once('/') {
            Some((ip, prefix_raw)) => (ip, prefix_raw.parse::<u8>().ok()?),
            None => (trimmed, 32),
        };
        if prefix > 32 {
            return None;
        }
        Some(Self {
            network: ip_raw.parse().ok()?,
            prefix,
        })
    }

    fn sample_hosts(&self, limit: usize) -> Vec<IpAddr> {
        let host_bits = 32_u32.saturating_sub(self.prefix as u32);
        let size = if host_bits == 32 {
            u32::MAX
        } else {
            1_u32 << host_bits
        };
        let mask = if self.prefix == 0 {
            0
        } else {
            !0_u32 << host_bits
        };
        let base = u32::from(self.network) & mask;
        let start = if self.prefix >= 31 { 0 } else { 1 };
        let usable = if self.prefix >= 31 {
            size
        } else {
            size.saturating_sub(2)
        };
        let count = usable.min(limit as u32);
        (0..count)
            .map(|offset| {
                IpAddr::V4(Ipv4Addr::from(
                    base.saturating_add(start).saturating_add(offset),
                ))
            })
            .collect()
    }
}

fn parse_args() -> ScanConfig {
    let mut cfg = ScanConfig::default();
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--max-ip" | "-n" => {
                cfg.max_ip = args
                    .next()
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(cfg.max_ip)
            }
            "--max-latency" => {
                cfg.max_latency_ms = args
                    .next()
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(cfg.max_latency_ms)
            }
            "--attempts" => {
                cfg.attempts = args
                    .next()
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(cfg.attempts)
            }
            "--timeout" => {
                cfg.connect_timeout_ms = args
                    .next()
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(cfg.connect_timeout_ms)
            }
            "--input" | "-i" => {
                cfg.input_file = PathBuf::from(
                    args.next()
                        .unwrap_or_else(|| cfg.input_file.display().to_string()),
                )
            }
            "--help" | "-h" => {
                print_help();
                std::process::exit(0);
            }
            _ => {}
        }
    }
    cfg
}

fn print_help() {
    println!("Pluribus Scanner Rust UI");
    println!("Usage: cargo run -- [--input ../ipv4.txt] [--max-ip 10] [--max-latency 1000]");
    println!("\nOptions:");
    println!("  -i, --input <file>       IPv4 CIDR list (default: ../ipv4.txt)");
    println!("  -n, --max-ip <count>     Number of clean IP candidates to keep");
    println!("      --max-latency <ms>   Maximum average TCP latency");
    println!("      --attempts <count>   TCP attempts per IP");
    println!("      --timeout <ms>       Per-attempt connect timeout");
}

fn load_candidates(cfg: &ScanConfig) -> io::Result<Vec<IpAddr>> {
    let raw = fs::read_to_string(&cfg.input_file)?;
    let mut ips = Vec::new();
    for cidr in raw.lines().filter_map(Ipv4Cidr::parse) {
        let remaining = cfg.max_ip.saturating_mul(50).saturating_sub(ips.len());
        if remaining == 0 {
            break;
        }
        ips.extend(cidr.sample_hosts(remaining.min(256)));
    }
    Ok(ips)
}

fn measure_ip(ip: IpAddr, cfg: &ScanConfig) -> ScanResult {
    let mut latencies = Vec::new();
    let timeout = Duration::from_millis(cfg.connect_timeout_ms);
    for _ in 0..cfg.attempts.max(1) {
        let addr = SocketAddr::new(ip, 443);
        let start = Instant::now();
        if TcpStream::connect_timeout(&addr, timeout).is_ok() {
            latencies.push(start.elapsed().as_millis());
        }
    }

    if latencies.is_empty() {
        return ScanResult {
            ip,
            latency_ms: cfg.connect_timeout_ms as u128,
            jitter_ms: cfg.connect_timeout_ms as u128,
            loss_percent: 100.0,
            reachable: false,
        };
    }

    let latency_ms = latencies.iter().sum::<u128>() / latencies.len() as u128;
    let jitter_ms = if latencies.len() > 1 {
        latencies
            .windows(2)
            .map(|pair| pair[0].abs_diff(pair[1]))
            .sum::<u128>()
            / (latencies.len() - 1) as u128
    } else {
        0
    };
    let loss_percent = 100.0 * (1.0 - (latencies.len() as f64 / cfg.attempts.max(1) as f64));

    ScanResult {
        ip,
        latency_ms,
        jitter_ms,
        loss_percent,
        reachable: latency_ms <= cfg.max_latency_ms,
    }
}

fn render_ui(results: &[ScanResult], cfg: &ScanConfig) {
    print!("\x1B[2J\x1B[1;1H");
    println!("┌──────────────────────────────────────────────────────────────┐");
    println!("│ Pluribus Scanner - Rust terminal UI                          │");
    println!("├──────────────────────────────────────────────────────────────┤");
    println!(
        "│ target: {:>3} IPs │ max latency: {:>5} ms │ attempts: {:>2}       │",
        cfg.max_ip, cfg.max_latency_ms, cfg.attempts
    );
    println!("└──────────────────────────────────────────────────────────────┘\n");
    println!("| # | IP              | Latency | Jitter | Loss  | Status   |");
    println!("|---|-----------------|---------|--------|-------|----------|");
    for (idx, item) in results.iter().enumerate() {
        let status = if item.reachable { "clean" } else { "skip" };
        println!(
            "|{:>2} | {:<15} | {:>5}ms | {:>4}ms | {:>4.0}% | {:<8} |",
            idx + 1,
            item.ip,
            item.latency_ms,
            item.jitter_ms,
            item.loss_percent,
            status
        );
    }
    let _ = io::stdout().flush();
}

fn write_outputs(results: &[ScanResult]) -> io::Result<()> {
    let clean: Vec<&ScanResult> = results.iter().filter(|r| r.reachable).collect();
    fs::write(
        "selected-ips.txt",
        clean
            .iter()
            .map(|r| r.ip.to_string())
            .collect::<Vec<_>>()
            .join("\n"),
    )?;
    let mut csv = String::from("#,IP,Latency (ms),Jitter (ms),Loss (%),Reachable\n");
    for (idx, row) in clean.iter().enumerate() {
        csv.push_str(&format!(
            "{},{},{},{},{:.1},{}\n",
            idx + 1,
            row.ip,
            row.latency_ms,
            row.jitter_ms,
            row.loss_percent,
            row.reachable
        ));
    }
    fs::write("selected-ips.csv", csv)
}

fn main() -> io::Result<()> {
    let cfg = parse_args();
    let candidates = load_candidates(&cfg)?;
    let mut results = Vec::new();

    for ip in candidates {
        let result = measure_ip(ip, &cfg);
        if result.reachable {
            results.push(result);
            results.sort_by(|a, b| a.score().partial_cmp(&b.score()).unwrap_or(Ordering::Equal));
            results.truncate(cfg.max_ip);
            render_ui(&results, &cfg);
        }
        if results.len() >= cfg.max_ip {
            break;
        }
    }

    render_ui(&results, &cfg);
    write_outputs(&results)?;
    println!("\nSaved selected-ips.txt and selected-ips.csv");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_plain_ip_as_single_host() {
        let cidr = Ipv4Cidr::parse("192.0.2.10").expect("valid IPv4");
        assert_eq!(cidr.prefix, 32);
        assert_eq!(
            cidr.sample_hosts(5),
            vec![IpAddr::V4(Ipv4Addr::new(192, 0, 2, 10))]
        );
    }

    #[test]
    fn parses_cidr_and_samples_usable_hosts() {
        let cidr = Ipv4Cidr::parse("198.51.100.0/30").expect("valid CIDR");
        assert_eq!(
            cidr.sample_hosts(10),
            vec![
                IpAddr::V4(Ipv4Addr::new(198, 51, 100, 1)),
                IpAddr::V4(Ipv4Addr::new(198, 51, 100, 2))
            ]
        );
    }
}
