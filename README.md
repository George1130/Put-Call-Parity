# Put-Call-Parity
I am trying to create real world models while pursuing CFA.

📌 Overview
This project is a command-line Python tool that verifies the fundamental Put-Call Parity relationship using live options market data. It fetches real-time option chains via Yahoo Finance (yfinance), prices the options using the Cox-Ross-Rubinstein (CRR) Binomial Tree model, and compares the theoretical model prices and actual market prices to check for parity deviations.

By default, the script targets European-style options (like ^SPX or ^NDX) where exact put-call parity holds. It also features an experimental flag to evaluate American-style options by accounting for early exercise premiums.

✨ Features
Live Market Data: Fetches real-time spot prices, option chains, and implied volatilities using yfinance.

Dynamic Risk-Free Rate & Dividends: Automatically estimates the current risk-free rate using the 13-week T-bill (^IRX) and pulls continuous dividend yields directly from ticker metadata.

Binomial Option Pricing: Implements the Cox-Ross-Rubinstein (CRR) binomial tree to theoretically price both Call and Put options.

Parity Error Analysis: Calculates and displays the absolute parity error for both the theoretical model and the live market.

Customizable Parameters: Command-line arguments allow you to adjust binomial tree steps, moneyness bands, expiry dates, and manually override rates/yields.

Visualization & Export: Supports exporting the parity data table to CSV and generating graphical plots of Parity Error vs. Strike Price.

🧮 Mathematical Background
For European options, Put-Call Parity is defined as: $C - P = S \cdot e^{-qT} - K \cdot e^{-rT}$Where:C / P: Call / Put PriceS: Spot PriceK: Strike PriceT: Time to Expiry (in years)r: Risk-Free Interest Rateq: Continuous Dividend YieldThe script calculates the Left-Hand Side ($C - P$) for both the CRR Model and the Market, and subtracts the Right-Hand Side ($S \cdot e^{-qT} - K \cdot e^{-rT}$) to determine the "Parity Error". The model parity error should always be near zero (as the binomial tree is arbitrage-free by design), while the market error highlights bid/ask spreads, stale quotes, or American early-exercise premiums.

🚀 Installation
Clone the repository.

Install the required Python dependencies:
pip install -r requirements.txt

Usage
Run the script from the terminal. By default, it will analyze the nearest expiry for the S&P 500 Index (^SPX).
python main.py

Advanced Examples
1. Analyze a specific expiry date with a wider moneyness band and 500 binomial steps:
  python parity_verifier.py --ticker ^NDX --expiry 2024-01-19 --steps 500 --moneyness-band 0.20

2. Analyze an American-style equity option (e.g., AAPL), export to CSV, and plot the errors:
  python parity_verifier.py --ticker AAPL --american --csv aapl_parity.csv --plot

3. Manually override the risk-free rate and dividend yield:
  python parity_verifier.py --ticker ^SPX --rate 0.0525 --dividend-yield 0.015

🛠️ Command-Line ArgumentsArgumentDescriptionDefault--tickerUnderlying ticker symbol (prefer European-style like ^SPX).^SPX--expiryExpiry date YYYY-MM-DD.Nearest expiry--stepsNumber of steps in the CRR binomial tree.200--americanAllow early exercise pricing (American-style).False--moneyness-bandKeep strikes within +/- this fraction of the spot price.0.15--rateOverride the risk-free rate (decimal, e.g., 0.05).Auto-fetched from ^IRX--dividend-yieldOverride the continuous dividend yield (decimal).Auto-fetched--csvFile path to save the generated parity table as a CSV.None--plotGenerate and save a plot of Parity Error vs. Strike Price.False
