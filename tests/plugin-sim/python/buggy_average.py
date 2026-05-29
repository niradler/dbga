def average(nums):
    total = sum(nums)
    return total / len(nums)


def main():
    datasets = [[10, 20, 30], []]
    for ds in datasets:
        print(average(ds))


if __name__ == "__main__":
    main()
