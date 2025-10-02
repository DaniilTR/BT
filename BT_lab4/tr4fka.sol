// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract tr4fka is ERC20, Ownable {
    constructor() ERC20("Tr4fkaToken", "TR4F") Ownable(msg.sender) {
        uint256 initialAmount = 1000 * 10 ** decimals();

        // Сначала проверяем деплой только на создателя
        _mint(msg.sender, initialAmount);
    }

    function mint(address to, uint256 amount) external onlyOwner {
        _mint(to, amount);
    }

    function decimals() public pure override returns (uint8) {
        return 8;
    }
}
