-- xfan_video 建表语句
-- 请在下方粘贴完整的 CREATE TABLE SQL

CREATE TABLE `xfan_video` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键',
  `user_id` varchar(50) NOT NULL DEFAULT '' COMMENT '创建者用户 ID',
  `character_id` bigint NOT NULL DEFAULT '0' COMMENT '角色 ID',
  `service_level_limits` tinyint NOT NULL DEFAULT '0' COMMENT '服务等级，数字越大限制级越高',
  `price` int NOT NULL DEFAULT '0' COMMENT '所需金币数量',
  `title` varchar(100) NOT NULL COMMENT '视频标题',
  `video_url` varchar(255) NOT NULL COMMENT '视频 URL',
  `instruct_url` varchar(255) CHARACTER SET utf8mb3 COLLATE utf8mb3_general_ci NOT NULL DEFAULT '' COMMENT '指令地址',
  `cover_url` varchar(255) DEFAULT NULL COMMENT '封面图 URL',
  `cover_height` int NOT NULL DEFAULT '0' COMMENT '封面图片高度，px',
  `cover_width` int NOT NULL DEFAULT '0' COMMENT '封面图片宽度，px',
  `duration` int NOT NULL DEFAULT '0' COMMENT '视频时长(秒)',
  `show_order` int NOT NULL DEFAULT '0' COMMENT '排序',
  `deleted_flag` tinyint NOT NULL DEFAULT '1' COMMENT '删除标记(1:正常 -1:已删除)',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `click_count` int NOT NULL DEFAULT '0' COMMENT '点击次数',
  `background` tinyint DEFAULT '0' COMMENT '是否默认背景',
  PRIMARY KEY (`id`),
  KEY `idx_character_id` (`character_id`)
) ENGINE=InnoDB AUTO_INCREMENT=46537 DEFAULT CHARSET=utf8mb3 COMMENT='视频资源表';