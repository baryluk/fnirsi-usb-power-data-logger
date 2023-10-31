import pandas as pd
import sys
import glob
import os
from pathlib import Path

def main():
   
    means = None

    for directory in sys.argv[1:]:
        base = Path(directory)
        files = base.glob("*txt")
        for filename in files:
            df = pd.read_csv(filename, index_col=None, header=0, delimiter=" ")
            aux_df = df.mean().to_frame().T
            aux_df['name'] = [os.path.basename(filename)[:-4]]
            if means is None:
                means = aux_df
            else:
                means = pd.concat([means, aux_df])

    means.to_csv("means_comparison.csv")


if __name__ == '__main__':
    main()
