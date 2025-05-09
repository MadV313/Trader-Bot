function getVariants(itemData) {
    if (itemData && typeof itemData === 'object') {
        return Object.keys(itemData);
    }
    return ["Default"];
}

function variantExists(variants, userChoice) {
    return variants.some(v => v.toLowerCase() === userChoice.toLowerCase());
}

module.exports = { getVariants, variantExists };
