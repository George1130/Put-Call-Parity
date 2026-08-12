# Put-Call Parity Verifier using the CRR Binomial Model

## 📌 Overview
This project is a command-line Python tool that verifies the fundamental **Put-Call Parity** relationship using live options market data. It fetches real-time option chains via Yahoo Finance (`yfinance`), prices the options using the **Cox-Ross-Rubinstein (CRR) Binomial Tree model**, and compares the theoretical model prices with actual market prices to check for parity deviations.

By default, the script targets European-style options (like `^SPX` or `^NDX`) where exact put-call parity holds. It also features an optional flag to evaluate American-style options by accounting for early exercise premiums.

## ✨ Features
* **Live Market Data:** Fetches real-time spot prices, option chains, and implied volatilities using `yfinance`.
* **Dynamic Risk-Free Rate & Dividends:** Automatically estimates the current risk-free rate using the 13-week T-bill (`^IRX`) and pulls continuous dividend yields directly from ticker metadata.
* **Binomial Option Pricing:** Implements the Cox-Ross-Rubinstein (CRR) binomial tree to theoretically price both Call and Put options.
* **Parity Error Analysis:** Calculates and displays the absolute parity error for both the theoretical model and the live market. 
* **Customizable Parameters:** Command-line arguments allow you to adjust binomial tree steps, moneyness bands, expiry dates, and manually override rates/yields.
* **Visualization & Export:** Supports exporting the parity data table to CSV and generating graphical plots of Parity Error vs. Strike Price.

## 🧮 Mathematical Background
For European options, Put-Call Parity is defined as:

**C - P = S * e^(-qT) - K * e^(-rT)**

Where:
* **C / P:** Call / Put Price
* **S:** Spot Price
* **K:** Strike Price
* **T:** Time to Expiry (in years)
* **r:** Risk-Free Interest Rate
* **q:** Continuous Dividend Yield

The script calculates the Left-Hand Side (C - P) for both the CRR Model and the Market, and subtracts the Right-Hand Side (S * e^(-qT) - K * e^(-rT)) to determine the "Parity Error". The model parity error should always be near zero (as the binomial tree is arbitrage-free by design), while the market error highlights bid/ask spreads, stale quotes, or American early-exercise premiums.

## 🚀 Installation

1. Clone the repository to your local machine.
2. Install the required Python dependencies:

```bash
pip install -r requirements.txt
```

3. Run the Script:
```
python main.py
```

## Advanced Examples
1. Analyze a specific expiry date with a wider moneyness band and 500 binomial steps:

```bash
python main.py --ticker ^NDX --expiry 2024-01-19 --steps 500 --moneyness-band 0.20
```
2. Analyze an American-style equity option (e.g., AAPL), export to CSV, and plot the errors:

```bash
python main.py --ticker AAPL --american --csv aapl_parity.csv --plot
```

3. Manually override the risk-free rate and dividend yield:
```bash
python main.py --ticker ^SPX --rate 0.0525 --dividend-yield 0.015
```
