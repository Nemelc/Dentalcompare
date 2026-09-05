(() => {
  const txt=document.body?.innerText||"";
  const title=document.querySelector("h1")?.innerText?.trim()||document.title;
  const refRe=/Réf\.\s*GACD\s*:\s*([A-Z0-9-]+)/gi;
  const fabRe=/Réf\.\s*Fabricant\s*:\s*([A-Z0-9+._ /-]+)/i;
  const priceRe=/(\d{1,5}(?:[ .]\d{3})*[,.]\d{2})\s*€/;
  const stocks=["En stock","Sur commande","En réapprovisionnement","Arrêté"];
  const ms=[...txt.matchAll(refRe)], products=[];
  const priceToNumber=s=>Number(s.replace(/\u202f/g,"").replace(/ /g,"").replace(/\./g,"").replace(",","."));
  ms.forEach((m,i)=>{
    const block=txt.slice(m.index,i+1<ms.length?ms[i+1].index:txt.length), fab=block.match(fabRe), price=block.match(priceRe);
    products.push({merchant:"GACD",merchant_reference:m[1],manufacturer_reference:fab?fab[1].trim():null,name:title,price_eur:price?priceToNumber(price[1]):null,availability:stocks.find(s=>block.toLowerCase().includes(s.toLowerCase()))||null,source_url:location.href,captured_at:new Date().toISOString()});
  });
  const payload={source:"gacd_browser_capture",page_title:title,source_url:location.href,captured_at:new Date().toISOString(),products};
  const blob=new Blob([JSON.stringify(payload,null,2)],{type:"application/json"}), a=document.createElement("a");
  a.href=URL.createObjectURL(blob); a.download=`gacd_${new Date().toISOString().replace(/[:.]/g,"-")}.json`; a.click(); setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  alert(`${products.length} référence(s) capturée(s)`);
})();
