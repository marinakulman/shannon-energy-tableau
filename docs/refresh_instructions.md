# Refreshing the data

1. Place the new source CSV files in `data/raw/`. **Never edit the source files.**

2. Update the cut-off date in `scripts/prepare_data.py`:

   ```python
   DATA_AS_OF = pd.Timestamp('YYYY-MM-DD')
   ```

   The cut-off date is changed here, together with the dataset - never by switching a
   control in the Tableau interface. Keeping it in one place is what makes the analysis
   reproducible.

3. Run the pipeline:

   ```bash
   python3 scripts/prepare_data.py
   ```

4. Check the control table printed at the end of the run. **Every row must read `OK`.**

   If a value does not match, **do not adjust the formulas to fit the expected number.**
   Find the cause first. The usual suspects are whitespace in key columns, duplicate rows,
   date format inconsistencies, the grain at which a join was made, the `LEG` channel,
   observability flags, or the scope a filter is applied at.

5. Check `docs/` for `unmapped_channels.csv` and `conflicts_duplicate_customerid.csv`.
   These files are written only when a problem is detected - their presence means the run
   found something that needs a decision.

6. In Tableau, refresh the extracts and update the `DataAsOf` constant to match.

## Requirements

Python 3 with `pandas` and `numpy`. The script reads and writes local files only; it sends
nothing to any external service.
