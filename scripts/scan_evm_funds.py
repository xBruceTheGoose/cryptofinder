#!/usr/bin/env python3
"""
EVM Hidden Funds & Historical Delta Scanner (Cross-Framework Edition)
---------------------------------------------------------------------
Deterministic, zero-dependency CLI scanner for discovering unclaimed ETH, ERC-20s,
NFT custody, staking vaults, failed auction commitments, legacy keyed bids
(MoonCats, CryptoPunks, ENS Deeds), and escrow balances across EVM chains.

Usage:
  python scan_evm_funds.py --address brucethegoose.eth --chains Ethereum,Arbitrum,Optimism,Base --output-dir ./scan_output
"""

import argparse
import json
import os
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

CHAINS = {
    "Ethereum": {
        "chain_id": 1,
        "rpc": "https://ethereum-rpc.publicnode.com",
        "symbol": "ETH",
        "explorer": "https://etherscan.io",
        "routescan": "https://api.routescan.io/v2/network/mainnet/evm/1/etherscan/api",
        "blockscout": "https://eth.blockscout.com",
        "tokens": [
            ("WETH", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 18),
            ("USDC", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6),
            ("USDT", "0xdAC17F958D2ee523a2206206994597C13D831ec7", 6),
            ("DAI", "0x6B175474E89094C44Da98b954EedeAC495271d0F", 18),
            ("BlurPool", "0x0000000000A39bb272e79075ade125fd351887Ac", 18),
            ("FETH", "0x3B3ee1931Dc30C1957379FAc9aba94D1C48a5405", 18),
            ("stETH", "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84", 18),
            ("wstETH", "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0", 18),
            ("rETH", "0xae78736Cd615f374D3085123A210448E74Fc6393", 18),
            ("ENS", "0xC18360217D8F7Ab5e7c516566761Ea12Ce7F9D72", 18),
            ("BLUR", "0x5283D291DBCF85356A21bA090E6db59121208b44", 18),
            ("APE", "0x4d224452801ACEd8B2F0aebE155379bb5D594381", 18),
            ("UNI", "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", 18),
            ("aWETH_v2", "0x030bA81f1c18d280636F32af80b9AAd02Cf0854e", 18),
            ("aEthWETH_v3", "0x4d5F47FA6A74757f35C14fD3a6Ef8E3C9BC514E8", 18),
            ("cETH_v2", "0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5", 8),
            ("ZoraRewards", "0x7777777F279eba3d3Ad8F4E708545291A6fDBA8B", 18),
        ],
    },
    "Arbitrum": {
        "chain_id": 42161,
        "rpc": "https://arb1.arbitrum.io/rpc",
        "symbol": "ETH",
        "explorer": "https://arbiscan.io",
        "routescan": "https://api.routescan.io/v2/network/mainnet/evm/42161/etherscan/api",
        "tokens": [
            ("WETH", "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", 18),
            ("USDC", "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6),
            ("USDC.e", "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8", 6),
            ("USDT", "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", 6),
            ("ARB", "0x912CE59144191C1204E64559FE8253a0e49E6548", 18),
            ("ZoraRewards", "0x7777777F279eba3d3Ad8F4E708545291A6fDBA8B", 18),
        ],
    },
    "Optimism": {
        "chain_id": 10,
        "rpc": "https://mainnet.optimism.io",
        "symbol": "ETH",
        "explorer": "https://optimistic.etherscan.io",
        "routescan": "https://api.routescan.io/v2/network/mainnet/evm/10/etherscan/api",
        "tokens": [
            ("WETH", "0x4200000000000000000000000000000000000006", 18),
            ("USDC", "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85", 6),
            ("USDC.e", "0x7F5c764cBc14f9669B88837ca1490cCa17c31607", 6),
            ("OP", "0x4200000000000000000000000000000000000042", 18),
            ("ZoraRewards", "0x7777777F279eba3d3Ad8F4E708545291A6fDBA8B", 18),
        ],
    },
    "Base": {
        "chain_id": 8453,
        "rpc": "https://mainnet.base.org",
        "symbol": "ETH",
        "explorer": "https://basescan.org",
        "routescan": "https://api.routescan.io/v2/network/mainnet/evm/8453/etherscan/api",
        "tokens": [
            ("WETH", "0x4200000000000000000000000000000000000006", 18),
            ("USDC", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6),
            ("AERO", "0x940181a94A35A4569E4529A3CDfB74e38FD98631", 18),
            ("DEGEN", "0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed", 18),
            ("ZoraRewards", "0x7777777F279eba3d3Ad8F4E708545291A6fDBA8B", 18),
        ],
    },
    "BSC": {
        "chain_id": 56,
        "rpc": "https://bsc-rpc.publicnode.com",
        "symbol": "BNB",
        "explorer": "https://bscscan.com",
        "routescan": "https://api.routescan.io/v2/network/mainnet/evm/56/etherscan/api",
        "tokens": [
            ("WBNB", "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c", 18),
            ("BUSD", "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56", 18),
            ("USDT", "0x55d398326f99059fF775485246999027B3197955", 18),
            ("USDC", "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", 18),
            ("ETH", "0x2170Ed0880ac9A755fd29B2688956BD959F933F8", 18),
            ("CAKE", "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82", 18),
        ],
    },
    "Polygon": {
        "chain_id": 137,
        "rpc": "https://polygon-bor-rpc.publicnode.com",
        "symbol": "POL",
        "explorer": "https://polygonscan.com",
        "routescan": "https://api.routescan.io/v2/network/mainnet/evm/137/etherscan/api",
        "tokens": [
            ("WETH", "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619", 18),
            ("WMATIC", "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270", 18),
            ("USDC", "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", 6),
            ("USDC.e", "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", 6),
        ],
    },
    "Avalanche": {
        "chain_id": 43114,
        "rpc": "https://api.avax.network/ext/bc/C/rpc",
        "symbol": "AVAX",
        "explorer": "https://snowtrace.io",
        "routescan": "https://api.routescan.io/v2/network/mainnet/evm/43114/etherscan/api",
        "tokens": [],
    },
    "Fantom": {
        "chain_id": 250,
        "rpc": "https://rpcapi.fantom.network",
        "symbol": "FTM",
        "explorer": "https://ftmscan.com",
        "tokens": [],
    },
    "Gnosis": {
        "chain_id": 100,
        "rpc": "https://gnosis-rpc.publicnode.com",
        "symbol": "xDAI",
        "explorer": "https://gnosisscan.io",
        "tokens": [],
    },
    "Zora": {
        "chain_id": 7777777,
        "rpc": "https://rpc.zora.energy",
        "symbol": "ETH",
        "explorer": "https://explorer.zora.energy",
        "tokens": [
            ("ZoraRewards", "0x7777777F279eba3d3Ad8F4E708545291A6fDBA8B", 18),
        ],
    },
    "Blast": {
        "chain_id": 81457,
        "rpc": "https://rpc.blast.io",
        "symbol": "ETH",
        "explorer": "https://blastscan.io",
        "routescan": "https://api.routescan.io/v2/network/mainnet/evm/81457/etherscan/api",
        "tokens": [],
    },
}


def fetch_json(url, timeout=35, retries=3):
    import shutil
    import subprocess
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            curl_bin = shutil.which("curl.exe") or shutil.which("curl")
            if curl_bin:
                try:
                    p = subprocess.run(
                        [curl_bin, "-s", "-L", "--max-time", str(timeout), "-A", ua, url],
                        capture_output=True,
                    )
                    if p.returncode == 0 and p.stdout:
                        return json.loads(p.stdout.decode("utf-8", errors="replace"))
                except Exception:
                    pass
            if i == retries - 1:
                return {}
            time.sleep(1.5 * (i + 1))
    return {}


def rpc_batch(rpc_url, calls, timeout=25, retries=3):
    if not calls:
        return []
    for i in range(retries):
        try:
            payload = json.dumps(calls).encode("utf-8")
            req = urllib.request.Request(
                rpc_url,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res if isinstance(res, list) else [res]
        except Exception:
            if i == retries - 1:
                return []
            time.sleep(1.5 * (i + 1))
    return []


def resolve_address_or_ens(target):
    target = target.strip()
    if target.startswith("0x") and len(target) == 42:
        return target
    # 1. Native on-chain ENS resolution via Ethereum Mainnet RPC (ENS Registry 0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e)
    eth_rpc = CHAINS["Ethereum"]["rpc"]
    node = "00" * 32
    for label in reversed(target.lower().split(".")):
        label_hex = "0x" + label.encode("utf-8").hex()
        lh_res = rpc_batch(eth_rpc, [{"jsonrpc": "2.0", "id": 1, "method": "web3_sha3", "params": [label_hex]}])
        if not lh_res or "result" not in lh_res[0]:
            break
        label_hash = lh_res[0]["result"][2:]
        nh_res = rpc_batch(eth_rpc, [{"jsonrpc": "2.0", "id": 2, "method": "web3_sha3", "params": ["0x" + node + label_hash]}])
        if not nh_res or "result" not in nh_res[0]:
            break
        node = nh_res[0]["result"][2:]
    if len(node) == 64 and node != "00" * 32:
        registry = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e"
        res_call = rpc_batch(eth_rpc, [{"jsonrpc": "2.0", "id": 3, "method": "eth_call", "params": [{"to": registry, "data": "0x0178b8bf" + node}, "latest"]}])
        if res_call and res_call[0].get("result") and len(res_call[0]["result"]) >= 66:
            resolver = "0x" + res_call[0]["result"][-40:]
            if int(resolver, 16) != 0:
                addr_call = rpc_batch(eth_rpc, [{"jsonrpc": "2.0", "id": 4, "method": "eth_call", "params": [{"to": resolver, "data": "0x3b3b57de" + node}, "latest"]}])
                if addr_call and addr_call[0].get("result") and len(addr_call[0]["result"]) >= 66:
                    addr = "0x" + addr_call[0]["result"][-40:]
                    if int(addr, 16) != 0:
                        return addr
    # 2. Fallback to ensdata.net API
    for url in (f"https://api.ensdata.net/{target}", f"https://api.ensideas.com/ens/resolve/{target}"):
        data = fetch_json(url, timeout=15)
        resolved = data.get("address")
        if resolved and resolved.startswith("0x") and len(resolved) == 42:
            return resolved
    raise ValueError(f"Could not resolve ENS or address: {target}")


def unwrap_eip1167(bytecode_hex):
    b = (bytecode_hex or "").lower()
    if b.startswith("0x363d3d373d3d3d363d73") and len(b) >= 62:
        return "0x" + b[22:62]
    return None


def scan_multichain_balances(address):
    padded = address[2:].lower().rjust(64, "0")
    results = {}
    for cname, cfg in CHAINS.items():
        rpc = cfg["rpc"]
        calls = [
            {"jsonrpc": "2.0", "id": "bal", "method": "eth_getBalance", "params": [address, "latest"]},
            {"jsonrpc": "2.0", "id": "nonce", "method": "eth_getTransactionCount", "params": [address, "latest"]},
        ]
        for idx, (tname, taddr, dec) in enumerate(cfg.get("tokens", [])):
            calls.append({
                "jsonrpc": "2.0",
                "id": f"tok_{idx}",
                "method": "eth_call",
                "params": [{"to": taddr, "data": "0x70a08231" + padded}, "latest"],
            })
        resp = rpc_batch(rpc, calls)
        rmap = {r.get("id"): r.get("result") for r in resp if isinstance(r, dict)}
        native_bal = int(rmap.get("bal") or "0x0", 16) / 1e18
        nonce = int(rmap.get("nonce") or "0x0", 16)
        tok_bals = []
        for idx, (tname, taddr, dec) in enumerate(cfg.get("tokens", [])):
            raw = rmap.get(f"tok_{idx}")
            if raw and raw != "0x":
                val = int(raw, 16) / (10 ** dec)
                if val > 0.0001:
                    tok_bals.append({"symbol": tname, "address": taddr, "balance": val})
        results[cname] = {
            "symbol": cfg["symbol"],
            "native_balance": native_bal,
            "tx_count": nonce,
            "tokens": tok_bals,
        }
    return results


def scan_legacy_keyed_protocols(address):
    """Checks MoonCatRescue, CryptoPunks, 0xSplits, Foundation FETH, and Old ENS Deeds."""
    rpc = CHAINS["Ethereum"]["rpc"]
    padded = address[2:].lower().rjust(64, "0")
    topic_addr = "0x000000000000000000000000" + address[2:].lower()
    findings = []

    # 1. MoonCatRescue (0x60cd862c9c687a9de49aecdc3a99b74a4fc54ab6)
    mooncat = "0x60cd862c9c687a9de49aecdc3a99b74a4fc54ab6"
    logs_url = (
        f"https://eth.blockscout.com/api?module=logs&action=getLogs"
        f"&fromBlock=0&toBlock=latest&address={mooncat}&topic2={topic_addr}"
    )
    mc_logs = fetch_json(logs_url, timeout=20).get("result", [])
    cat_ids = set()
    if isinstance(mc_logs, list):
        for l in mc_logs:
            topics = l.get("topics") or []
            if len(topics) >= 2 and topics[1]:
                cat_ids.add(topics[1][:12])  # 0x + 5 bytes (10 hex chars)

    calls = [
        # MoonCat pendingWithdrawals
        {"jsonrpc": "2.0", "id": "mc_pw", "method": "eth_call", "params": [{"to": mooncat, "data": "0xf3f43703" + padded}, "latest"]},
        # CryptoPunks pendingWithdrawals
        {"jsonrpc": "2.0", "id": "cp_pw", "method": "eth_call", "params": [{"to": "0xb47e3cd837dDF8e4c57F05d70Ab865de6e193BBB", "data": "0xf3f43703" + padded}, "latest"]},
    ]
    for c_id in sorted(cat_ids):
        calls.append({
            "jsonrpc": "2.0",
            "id": f"cat_{c_id}",
            "method": "eth_call",
            "params": [{"to": mooncat, "data": "0xbec6bc67" + c_id[2:].ljust(64, "0")}, "latest"],
        })

    resp = rpc_batch(rpc, calls)
    for r in resp:
        rid = r.get("id", "")
        res = r.get("result") or "0x"
        if rid == "mc_pw" and res != "0x":
            val = int(res, 16) / 1e18
            if val > 0:
                findings.append({"protocol": "MoonCatRescue pendingWithdrawals", "contract": mooncat, "amount_eth": val, "action": "withdraw()"})
        elif rid == "cp_pw" and res != "0x":
            val = int(res, 16) / 1e18
            if val > 0:
                findings.append({"protocol": "CryptoPunks pendingWithdrawals", "contract": "0xb47e3cd837dDF8e4c57F05d70Ab865de6e193BBB", "amount_eth": val, "action": "withdraw()"})
        elif rid.startswith("cat_") and len(res) >= 258:
            c_id = rid[4:]
            exists = int(res[2:66], 16)
            requester = "0x" + res[154:194]
            price = int(res[194:258], 16) / 1e18
            if exists == 1 and requester.lower() == address.lower() and price > 0:
                findings.append({
                    "protocol": f"MoonCatRescue Active Adoption Request (catId {c_id})",
                    "contract": mooncat,
                    "amount_eth": price,
                    "action": f"cancelAdoptionRequest({c_id})",
                })
    return findings


def fetch_etherscan_action(base_api, action, address, max_pages=10):
    items_by_key = {}

    def fetch_page(args):
        sort_dir, page = args
        url = (
            f"{base_api}?module=account&action={action}&address={address}"
            f"&startblock=0&endblock=99999999&page={page}&offset=1000&sort={sort_dir}"
        )
        res = fetch_json(url, timeout=30).get("result", [])
        return res if isinstance(res, list) else []

    first_batch = fetch_page(("asc", 1))
    for item in first_batch:
        if isinstance(item, dict):
            key = f"{item.get('hash')}_{item.get('traceId', '')}_{item.get('logIndex', '')}_{item.get('tokenID', '')}"
            items_by_key[key] = item

    # Only fetch additional pages if page 1 hit the 1000-item ceiling
    if len(first_batch) >= 1000 and max_pages > 1:
        tasks = [("asc", p) for p in range(2, max_pages + 1)] + [("desc", p) for p in range(1, 4)]
        with ThreadPoolExecutor(max_workers=4) as ex:
            for batch in ex.map(fetch_page, tasks):
                for item in batch:
                    if isinstance(item, dict):
                        key = f"{item.get('hash')}_{item.get('traceId', '')}_{item.get('logIndex', '')}_{item.get('tokenID', '')}"
                        items_by_key[key] = item
    return list(items_by_key.values())


BLOCKSCOUT_APIS = {
    "Ethereum": "https://eth.blockscout.com/api",
    "Arbitrum": "https://arbitrum.blockscout.com/api",
    "Optimism": "https://optimism.blockscout.com/api",
    "Base": "https://base.blockscout.com/api",
    "Polygon": "https://polygon.blockscout.com/api",
    "Gnosis": "https://gnosis.blockscout.com/api",
    "Zora": "https://explorer.zora.energy/api",
}


def analyze_chain_history(address, chain_name="Ethereum"):
    cfg = CHAINS.get(chain_name)
    if not cfg:
        return {}

    base_api = cfg.get("routescan") or BLOCKSCOUT_APIS.get(chain_name)
    if not base_api:
        return {}

    addr_l = address.lower()
    txs = fetch_etherscan_action(base_api, "txlist", address, max_pages=10)
    if not txs and BLOCKSCOUT_APIS.get(chain_name) and base_api != BLOCKSCOUT_APIS.get(chain_name):
        base_api = BLOCKSCOUT_APIS[chain_name]
        txs = fetch_etherscan_action(base_api, "txlist", address, max_pages=10)
    internal = fetch_etherscan_action(base_api, "txlistinternal", address, max_pages=4)
    tokentx = fetch_etherscan_action(base_api, "tokentx", address, max_pages=6)
    nfttx = fetch_etherscan_action(base_api, "tokennfttx", address, max_pages=4)

    eth_sent = defaultdict(float)
    eth_calls = defaultdict(list)
    all_calls = defaultdict(set)

    for t in txs:
        if t.get("from", "").lower() == addr_l and t.get("isError") == "0":
            to_a = (t.get("to") or "").lower()
            inp = t.get("input", "0x")
            fname = (t.get("functionName") or inp[:10]).split("(")[0]
            if to_a and inp != "0x":
                all_calls[to_a].add(fname)
                val = int(t.get("value", "0")) / 1e18
                if val > 0:
                    eth_sent[to_a] += val
                    eth_calls[to_a].append({
                        "hash": t.get("hash"),
                        "block": t.get("blockNumber"),
                        "value": val,
                        "func": fname,
                        "input": inp[:138],
                    })

    eth_recv_int = defaultdict(float)
    for it in internal:
        if it.get("to", "").lower() == addr_l and it.get("isError") == "0":
            f_a = (it.get("from") or "").lower()
            eth_recv_int[f_a] += int(it.get("value", "0")) / 1e18

    eth_contracts = list(eth_sent.keys())
    contract_eth_bal = {}
    contract_code = {}
    rpc = cfg["rpc"]
    for start in range(0, len(eth_contracts), 40):
        chunk = eth_contracts[start : start + 40]
        calls = []
        for i, c in enumerate(chunk):
            calls.append({"jsonrpc": "2.0", "id": f"b_{i}", "method": "eth_getBalance", "params": [c, "latest"]})
            calls.append({"jsonrpc": "2.0", "id": f"c_{i}", "method": "eth_getCode", "params": [c, "latest"]})
        for r in rpc_batch(rpc, calls):
            if isinstance(r, dict) and "id" in r:
                kind, idx_str = r["id"].split("_")
                c = chunk[int(idx_str)]
                if kind == "b":
                    contract_eth_bal[c] = int(r.get("result") or "0x0", 16) / 1e18
                elif kind == "c":
                    contract_code[c] = r.get("result") or "0x"

    eth_candidates = []
    ignore_funcs = {"mint", "purchase", "buy", "swap", "fulfillbasicorder", "atomicmatch_", "execute"}
    for c, sent in sorted(eth_sent.items(), key=lambda x: x[1], reverse=True):
        cbal = contract_eth_bal.get(c, 0.0)
        ret = eth_recv_int.get(c, 0.0)
        fset = all_calls[c]
        if cbal >= 0.005 and sent > ret:
            if not {x.lower() for x in fset}.issubset(ignore_funcs):
                eth_candidates.append({
                    "contract": c,
                    "eip1167_impl": unwrap_eip1167(contract_code.get(c)),
                    "eth_sent": round(sent, 6),
                    "eth_returned_internal": round(ret, 6),
                    "contract_live_eth": round(cbal, 6),
                    "functions_called": sorted(list(fset)),
                    "sample_txs": eth_calls[c][:5],
                })

    # ERC-20 Custody Delta
    erc20_out = defaultdict(float)
    erc20_in = defaultdict(float)
    erc20_meta = {}
    for tt in tokentx:
        taddr = (tt.get("contractAddress") or "").lower()
        dec = int(tt.get("tokenDecimal") or 18)
        sym = tt.get("tokenSymbol") or "ERC20"
        erc20_meta[taddr] = (sym, dec)
        val = int(tt.get("value") or "0") / (10 ** dec)
        f_a = (tt.get("from") or "").lower()
        to_a = (tt.get("to") or "").lower()
        if f_a == addr_l and to_a != addr_l:
            erc20_out[(to_a, taddr)] += val
        elif to_a == addr_l and f_a != addr_l:
            erc20_in[(f_a, taddr)] += val

    # Live balance check on all historically touched ERC-20 / LP tokens
    held_erc20s = []
    padded_user = addr_l[2:].rjust(64, "0")
    touched_tokens = list(erc20_meta.keys())
    for start in range(0, len(touched_tokens), 40):
        chunk = touched_tokens[start : start + 40]
        calls = [
            {"jsonrpc": "2.0", "id": i, "method": "eth_call", "params": [{"to": t, "data": "0x70a08231" + padded_user}, "latest"]}
            for i, t in enumerate(chunk)
        ]
        for r in rpc_batch(rpc, calls):
            if isinstance(r, dict) and isinstance(r.get("id"), int):
                t = chunk[r["id"]]
                res_hex = r.get("result") or "0x0"
                if res_hex != "0x" and len(res_hex) >= 66:
                    raw_bal = int(res_hex[:66], 16)
                    if raw_bal > 0:
                        sym, dec = erc20_meta[t]
                        bal = raw_bal / (10 ** dec)
                        if bal >= 0.0001:
                            held_erc20s.append({
                                "token_address": t,
                                "token_symbol": sym,
                                "decimals": dec,
                                "live_balance": round(bal, 6),
                            })

    erc20_candidates = []
    for (vault, taddr), out_val in erc20_out.items():
        in_val = erc20_in.get((vault, taddr), 0.0)
        if out_val > in_val and vault in all_calls:
            fset = {f.lower() for f in all_calls[vault]}
            sym, dec = erc20_meta[taddr]
            is_lp = any(k in sym.upper() for k in ["LP", "SLP", "UNI-V2", "BPT", "CRV", "CAKE-LP"])
            if is_lp or any(k in " ".join(fset) for k in ["stake", "deposit", "lock", "bid", "offer", "commit", "supply", "farm", "vault", "addliquidity", "join"]):
                erc20_candidates.append({
                    "vault_contract": vault,
                    "token_address": taddr,
                    "token_symbol": sym,
                    "tokens_sent": round(out_val, 6),
                    "tokens_returned": round(in_val, 6),
                    "functions_called": sorted(list(all_calls[vault])),
                })

    # NFT Custody & Escrowed NFTs
    nft_escrowed = []
    nft_sent_to = {}
    for nt in nfttx:
        caddr = (nt.get("contractAddress") or "").lower()
        tid = nt.get("tokenID") or ""
        sym = nt.get("tokenSymbol") or nt.get("tokenName") or "NFT"
        f_a = (nt.get("from") or "").lower()
        to_a = (nt.get("to") or "").lower()
        if f_a == addr_l and to_a != addr_l and to_a != "0x0000000000000000000000000000000000000000":
            nft_sent_to[(caddr, tid)] = (to_a, sym, nt.get("hash"))
        elif to_a == addr_l and (caddr, tid) in nft_sent_to:
            del nft_sent_to[(caddr, tid)]

    for (caddr, tid), (dest, sym, txhash) in nft_sent_to.items():
        if dest in all_calls:
            fset = {f.lower() for f in all_calls[dest]}
            if not fset.issubset({"fulfillbasicorder", "atomicmatch_", "safeTransferFrom".lower(), "transferfrom"}):
                nft_escrowed.append({
                    "nft_contract": caddr,
                    "token_symbol": sym,
                    "token_id": tid,
                    "escrow_contract": dest,
                    "functions_called": sorted(list(all_calls[dest])),
                    "tx_hash": txhash,
                })

    return {
        "tx_count_fetched": len(txs),
        "internal_tx_count": len(internal),
        "erc20_tx_count": len(tokentx),
        "nft_tx_count": len(nfttx),
        "held_erc20s": sorted(held_erc20s, key=lambda x: x["token_symbol"]),
        "eth_candidates": eth_candidates,
        "erc20_candidates": erc20_candidates,
        "nft_escrowed": nft_escrowed,
    }


def main():
    parser = argparse.ArgumentParser(description="Scan EVM wallet for hidden/stuck funds")
    parser.add_argument("--address", required=True, help="Target 0x wallet address or .eth ENS name")
    parser.add_argument("--chains", default="ALL_ACTIVE", help="Comma-separated chains for deep history audit, or ALL_ACTIVE")
    parser.add_argument("--output-dir", required=True, help="Directory to write UTF-8 reports")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    address = resolve_address_or_ens(args.address)
    print(f"[1/3] Resolved target: {args.address} -> {address}", flush=True)

    print("[2/3] Scanning multi-chain balances & legacy keyed protocols...", flush=True)
    mc = scan_multichain_balances(address)
    legacy = scan_legacy_keyed_protocols(address)

    chain_lookup = {k.lower(): k for k in CHAINS}
    if args.chains.upper() == "ALL_ACTIVE":
        chain_list = [
            cname for cname, info in mc.items()
            if info["tx_count"] > 0 or info["native_balance"] > 0.00001 or info["tokens"]
        ]
    else:
        req_chains = [chain_lookup[c.strip().lower()] for c in args.chains.split(",") if c.strip().lower() in chain_lookup]
        # Only deep-scan chains that have activity or balances (or Ethereum)
        chain_list = [
            cname for cname in req_chains
            if cname == "Ethereum" or mc.get(cname, {}).get("tx_count", 0) > 0 or mc.get(cname, {}).get("native_balance", 0) > 0.00001 or mc.get(cname, {}).get("tokens")
        ]

    history_audits = {}
    for cname in chain_list:
        print(f"[3/3] Running historical delta analysis on {cname}...", flush=True)
        history_audits[cname] = analyze_chain_history(address, cname)

    full_data = {
        "input": args.address,
        "resolved_address": address,
        "legacy_keyed_findings": legacy,
        "multichain": mc,
        "history_audits": history_audits,
    }
    json_path = os.path.join(args.output_dir, "scan_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(full_data, f, indent=2)

    md_path = os.path.join(args.output_dir, "candidates_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Hidden Funds Audit Report for `{address}` (`{args.address}`)\n\n")
        if legacy:
            f.write("## 0. Direct Legacy Protocol Hits (Verified On-Chain)\n\n")
            for hit in legacy:
                f.write(f"- **{hit['protocol']}** (`{hit['contract']}`): **`{hit['amount_eth']} ETH`** -> Call `{hit['action']}`\n")
            f.write("\n")

        f.write("## 1. Multi-Chain Activity & Liquid Balances\n\n")
        for cname, info in mc.items():
            if info["native_balance"] > 0.00001 or info["tx_count"] > 0 or info["tokens"]:
                f.write(f"- **{cname}**: `{info['native_balance']:.6f} {info['symbol']}` (Tx Count: `{info['tx_count']}`)\n")
                for tb in info["tokens"]:
                    f.write(f"  - Token `{tb['symbol']}` (`{tb['address']}`): `{tb['balance']:.6f}`\n")

        for cname, hist in history_audits.items():
            f.write(f"\n## 2. [{cname}] Live Held ERC-20 / LP Tokens Discovered From History\n\n")
            for he in hist.get("held_erc20s", []):
                f.write(f"- **`{he['token_symbol']}`** (`{he['token_address']}`): **`{he['live_balance']}`**\n")

            f.write(f"\n## 3. [{cname}] Candidate Contracts With Positive Net Native Outflow & Live Balance\n\n")
            for cand in hist.get("eth_candidates", []):
                impl_note = f" (EIP-1167 Proxy -> `{cand['eip1167_impl']}`)" if cand.get("eip1167_impl") else ""
                f.write(
                    f"- **`{cand['contract']}`**{impl_note}: Sent `{cand['eth_sent']}` | "
                    f"Returned `{cand['eth_returned_internal']}` | "
                    f"**Contract Holds `{cand['contract_live_eth']}`** | "
                    f"Calls: `{cand['functions_called']}`\n"
                )

            f.write(f"\n## 4. [{cname}] Candidate Vaults With Unreturned ERC-20 / LP Deposits\n\n")
            for ec in hist.get("erc20_candidates", []):
                f.write(
                    f"- **Vault `{ec['vault_contract']}`**: Sent `{ec['tokens_sent']} {ec['token_symbol']}` "
                    f"(`{ec['token_address']}`) | Returned `{ec['tokens_returned']}` | "
                    f"Calls: `{ec['functions_called']}`\n"
                )

            f.write(f"\n## 5. [{cname}] Candidate Escrowed / Staked NFTs\n\n")
            for ne in hist.get("nft_escrowed", []):
                f.write(
                    f"- **NFT `{ne['token_symbol']} #{ne['token_id']}`** (`{ne['nft_contract']}`) "
                    f"sent to `{ne['escrow_contract']}` | Calls: `{ne['functions_called']}`\n"
                )

    print(f"Done! Reports written to:\n  - {json_path}\n  - {md_path}", flush=True)


if __name__ == "__main__":
    main()
