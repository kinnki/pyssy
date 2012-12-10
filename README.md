PI
本API基于Jiachen Yang所开发的[pyssy](https://github.com/yssy/pyssy)，在其基础上逐步完善饮水思源API的开发，目前基本完成API的读取部分，更多工作将在今后空闲期间完成。

### 术语约定
为便于理解api的含义，按以下约定
* topic -- 话题是由帖子的发起人产生
* article -- 文章是由用户对话题所进行的回复讨论

### 使用方法
* `/api/topics`

获取论坛首页数据，包括'推荐阅读', '十大热门', '分区十大'，返回json数据如下：

```
{
	    "recommendation": [
	            {
			                "api_link": "/api/topic/articles/MobileDev/1354974523", 
					            "author": "LuDerek/fcfarseer", 
						                "board": "MobileDev", 
								            "date": "Dec08 21:48:43", 
									                "href": "/bbstcon?board=MobileDev&reid=1354974523&file=M.1354974523.A", 
											            "title": "iPhone/iPad UI自动化测试指南"
												            },... ],
													        "top10": [
														        {
																            "api_link": "/api/topic/articles/LoveBridge/1354982331", 
																	                "author": "lazylamb", 
																			            "board": "LoveBridge", 
																				                "href": "/bbstcon?board=LoveBridge&reid=1354982331", 
																						            "title": "这是我的挂牌，也是我的故事"
																							            },...],
																								        "top10_dis(x)": [
																									        {
																											            "api_link": "/api/topic/articles/Graduate/1354979397", 
																												                "author": "WaiLianer", 
																														            "board": "Graduate", 
																															                "href": "/bbstcon?board=Graduate&reid=1354979397", 
																																	            "title": "#阿拉丁神灯#愿望第一弹（真的有华师妹纸啊~）"
																																		            },...]
}
```
***

* `/api/topic/articles/<board_name>/<reid>`

获取某个话题的所有讨论文章

* `/api/board/<board_name>[/<articles|topics>]`

获取指定版面的文章或者话题

* `/api/boards`

获取版面

* `/api/user/<userid>`

获取用户信息

* `/api/users/online`(Todo)

