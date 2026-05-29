package main

import "fmt"

func average(nums []int) int {
	total := 0
	for _, n := range nums {
		total += n
	}
	return total / len(nums)
}

func main() {
	data := []int{}
	fmt.Println(average(data))
}
