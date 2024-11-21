


def disjoint_sequence(node_id):
    # https://math.stackexchange.com/questions/51096/partition-of-n-into-infinite-number-of-infinite-disjoint-sets
    odd = 2*node_id - 1
    n = 1
    while True:
        yield odd * (2**n)
        n += 1
    return


def main():
    return


if __name__ == "__main__":
    main()
