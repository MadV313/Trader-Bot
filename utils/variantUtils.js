function getVariants(itemData) {
    // Return all variant keys if present, otherwise default to ["Default"]
    if (itemData && typeof itemData === 'object') {
        return Object.keys(itemData);
    }
    return ["Default"];
}

function variantExists(variants, userChoice) {
    if (!userChoice) return false;
    const choice = userChoice.toLowerCase();
    return variants.some(v => v.toLowerCase() === choice);
}

module.exports = {
    getVariants,
    variantExists
};
