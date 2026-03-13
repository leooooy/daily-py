CREATE TABLE `xgame_video` (
    `video_id` varchar(64) COLLATE utf8mb4_general_ci NOT NULL COMMENT '主键',
    `video_name` varchar(255) COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '视频名称',
    `video_url` varchar(255) COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '视频地址',
    `post_url` varchar(255) COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '封面地址',
    `post_height` int DEFAULT NULL COMMENT '图片高度，单位px',
    `post_width` int DEFAULT NULL COMMENT '图片宽度，单位px',
    `service_level_limits` tinyint DEFAULT NULL COMMENT '服务等级，数字越大限制级越高',
    `instruct_url` varchar(255) COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '指令地址',
    `image_count` int DEFAULT NULL COMMENT '图片数量',
    `image_urls` text COLLATE utf8mb4_general_ci COMMENT '图片地址',
    `use_count` int DEFAULT NULL COMMENT '使用次数',
    `rel_use_count` int NOT NULL DEFAULT '0' COMMENT '实际使用次数',
    `click_count` int NOT NULL DEFAULT '0' COMMENT '点击次数',
    `duration` bigint DEFAULT NULL COMMENT '时长，单位秒',
    `displayed` bit(1) NOT NULL COMMENT '是否展示',
    `show_order` int DEFAULT NULL COMMENT '显示顺序',
    `deleted_flag` int NOT NULL COMMENT '删除标记(1: 正常 -1: 已删除)',
    `create_user_id` varchar(64) COLLATE utf8mb4_general_ci NOT NULL COMMENT '创建者Id',
    `create_time` datetime NOT NULL COMMENT '创建时间',
    `update_user_id` varchar(64) COLLATE utf8mb4_general_ci NOT NULL COMMENT '更新者Id',
    `update_time` datetime NOT NULL COMMENT '最后更新时间',
    `vr_mode` int DEFAULT '0',
    `source_module` int NOT NULL DEFAULT '0' COMMENT '来源： 0：xgame入口 1：Remote入口',
    `face_swap` tinyint NOT NULL DEFAULT '1' COMMENT '是否支持换脸',
    PRIMARY KEY (`video_id`) USING BTREE,
    KEY `idx_source_module` (`source_module`) USING BTREE COMMENT 'source_module索引'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci ROW_FORMAT=DYNAMIC;


CREATE TABLE `xgame_video_image` (
     `image_id` bigint NOT NULL COMMENT '图片id',
     `video_id` varchar(32) NOT NULL COMMENT '视频id',
     `image_url` varchar(255) NOT NULL COMMENT '图片地址',
     `create_time` datetime NOT NULL COMMENT '创建时间',
     `update_time` datetime NOT NULL COMMENT '最后更新时间',
     PRIMARY KEY (`image_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=latin1 ROW_FORMAT=DYNAMIC COMMENT='xgame中视频图片表';